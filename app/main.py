"""FastAPI routes. All real work happens in the pure modules; this file only wires them to HTTP."""
from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import geometry, gcode, package3mf, paths
from .settings import Settings, load_settings, save_settings, settings_from_dict
from .svg_input import SvgResult, svg_to_polylines

STATIC_DIR = paths.resource_dir() / "static"
SETTINGS_PATH = paths.data_dir() / "settings.json"
SIMPLIFY_TOL_MM = 0.05
MAX_DRAWINGS = 20
MIN_HATCH_SPACING_MM = 0.1

app = FastAPI(title="P1S Pen Plotter")

# Uploaded drawings in source units with their stroke colours, kept in memory (most recent MAX_DRAWINGS).
_drawings: OrderedDict[str, SvgResult] = OrderedDict()


class PlacedSvg(BaseModel):
    """One uploaded SVG on the bed: width/height before rotating (mm; no height = keep proportions),
    centre (pen coordinates, mm), anticlockwise turn (degrees)."""

    id: str
    width_mm: float = Field(gt=0, le=geometry.BED_SIZE_MM)
    height_mm: float | None = Field(default=None, gt=0, le=geometry.BED_SIZE_MM)
    x_mm: float
    y_mm: float
    rotation_deg: float = 0.0


class FillStyle(BaseModel):
    """How to draw the filled areas of one colour: not at all, parallel hatch lines, or cross-hatching
    (a second set at 90 degrees). spacing_mm between lines; angle_deg anticlockwise from +X on the bed."""

    mode: Literal["none", "hatch", "cross"] = "none"
    spacing_mm: float = Field(default=1.0, ge=MIN_HATCH_SPACING_MM, le=50)
    angle_deg: float = 45.0


class LayoutRequest(BaseModel):
    """The SVGs on the bed, which pen draws which colours, and how filled areas are drawn.

    pens: one entry per pen in drawing order, each a list of SVG colours ("#rrggbb") that pen draws, across
    all SVGs. Colours left out are not drawn. None = one pen per colour, in order of first appearance.
    fills: fill style per fill colour; colours not listed are not filled (only their outlines are drawn).
    """

    items: list[PlacedSvg]
    name: str = "drawing"
    pens: list[list[str]] | None = None
    fills: dict[str, FillStyle] = {}


def _settings() -> Settings:
    return load_settings(SETTINGS_PATH)


def _get_drawing(drawing_id: str) -> SvgResult:
    try:
        return _drawings[drawing_id]
    except KeyError:
        raise HTTPException(404, "Drawing not found - please upload it again.") from None


def _hatching(drawing: SvgResult, item: PlacedSvg, fills: dict[str, FillStyle]) -> tuple[list[geometry.Polyline], list[str]]:
    """Hatch lines (bed mm) for the filled shapes of one placed SVG, with the fill colour of each line."""
    lines: list[geometry.Polyline] = []
    colours: list[str] = []
    for fill in drawing.fills:
        style = fills.get(fill.colour)
        if style is None or style.mode == "none":
            continue
        rings = geometry.place(fill.rings, item.width_mm, item.x_mm, item.y_mm, item.rotation_deg,
                               height_mm=item.height_mm, ref=drawing.polylines)
        angles = [style.angle_deg] + ([style.angle_deg + 90] if style.mode == "cross" else [])
        for angle in angles:
            new = geometry.hatch(rings, style.spacing_mm, angle, fill.evenodd)
            lines += new
            colours += [fill.colour] * len(new)
    return lines, colours


def _planned(req: LayoutRequest, s: Settings) -> list[gcode.Layer]:
    """Place every SVG (with hatch lines for filled areas), split all strokes into one layer per pen,
    then simplify and order each layer."""
    placed: list[geometry.Polyline] = []
    colours: list[str] = []
    fills = {c.lower(): f for c, f in req.fills.items()}
    for item in req.items:
        drawing = _get_drawing(item.id)
        placed += geometry.place(
            drawing.polylines, item.width_mm, item.x_mm, item.y_mm, item.rotation_deg, height_mm=item.height_mm
        )
        colours += drawing.colours
        lines, line_colours = _hatching(drawing, item, fills)
        placed += lines
        colours += line_colours
    pens = req.pens if req.pens is not None else [[c] for c in dict.fromkeys(colours)]
    layers = []
    for group in pens:
        wanted = {c.lower() for c in group}
        polys = [p for p, c in zip(placed, colours) if c in wanted]
        polys = geometry.optimise_order(geometry.clean(polys, SIMPLIFY_TOL_MM), gcode.pen_start(s))
        if polys:
            layers.append(gcode.Layer(group[0].lower(), polys))
    return layers


def _flat(layers: list[gcode.Layer]) -> list[geometry.Polyline]:
    return [p for layer in layers for p in layer.polylines]


def _summary(layers: list[gcode.Layer], s: Settings, problems: list[str]) -> dict[str, Any]:
    start = gcode.pen_start(s)
    draw_mm = travel_mm = 0.0
    for layer in layers:  # every pen starts at the front, where it was fitted
        d, t = geometry.path_lengths(layer.polylines, start)
        draw_mm, travel_mm = draw_mm + d, travel_mm + t
    polys = _flat(layers)
    return {
        "polylines": [[[round(x, 2), round(y, 2)] for x, y in p] for p in polys],
        "layers": [{"colour": layer.colour, "strokes": len(layer.polylines)} for layer in layers],
        "pen_start": list(start),
        "strokes": len(polys),
        "pen_changes": max(0, len(layers) - 1),
        "draw_mm": round(draw_mm, 1),
        "travel_mm": round(travel_mm, 1),
        "seconds": round(gcode.layers_seconds(layers, s)),
        "problems": problems,
    }


def _check(layers: list[gcode.Layer], s: Settings) -> list[str]:
    return gcode.check_job(_flat(layers), s, pen_changes=max(0, len(layers) - 1))


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "drawing"


def _download(job: gcode.Job, polys: list[geometry.Polyline], name: str, fmt: str) -> Response:
    name = _safe_name(name)
    if fmt == "gcode":
        return Response(job.gcode, media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{name}.gcode"'})
    data = package3mf.build_gcode_3mf(job.gcode, job.estimated_seconds, name, polys)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}.gcode.3mf"'})


def _job_or_400(build: Any) -> gcode.Job:
    try:
        return build()
    except gcode.BoundsError as exc:
        raise HTTPException(400, {"problems": exc.problems}) from None


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return asdict(_settings())


@app.put("/api/settings")
def put_settings(data: dict[str, Any]) -> dict[str, Any]:
    try:
        s = settings_from_dict(data)
    except (TypeError, ValueError):
        raise HTTPException(400, {"problems": ["All settings must be numbers."]}) from None
    problems = s.validate()
    if problems:
        raise HTTPException(400, {"problems": problems})
    save_settings(s, SETTINGS_PATH)
    return asdict(s)


def _colour_list(result: SvgResult) -> list[dict[str, Any]]:
    """Every stroke or fill colour with its stroke and filled-shape counts, in order of first appearance."""
    strokes, fills = result.colour_counts(), result.fill_counts()
    return [{"colour": c, "strokes": strokes.get(c, 0), "fills": fills.get(c, 0)} for c in dict.fromkeys([*strokes, *fills])]


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if not (file.filename or "").lower().endswith(".svg"):
        raise HTTPException(400, {"problems": ["Only SVG files are supported so far."]})
    try:
        result = svg_to_polylines(data)
    except ValueError as exc:
        raise HTTPException(400, {"problems": [str(exc)]}) from None
    drawing_id = uuid.uuid4().hex
    _drawings[drawing_id] = result
    while len(_drawings) > MAX_DRAWINGS:
        _drawings.popitem(last=False)
    min_x, min_y, max_x, max_y = geometry.bbox(result.polylines)
    return {
        "id": drawing_id,
        "name": Path(file.filename or "drawing").stem,
        "aspect": (max_y - min_y) / (max_x - min_x) if max_x > min_x else 1.0,
        "strokes": len(result.polylines),
        "colours": _colour_list(result),
        "warnings": result.warnings,
    }


@app.post("/api/plan")
def plan(req: LayoutRequest) -> dict[str, Any]:
    s = _settings()
    layers = _planned(req, s)
    return _summary(layers, s, _check(layers, s))


@app.post("/api/export")
def export(req: LayoutRequest, fmt: str = "3mf") -> Response:
    s = _settings()
    layers = _planned(req, s)
    job = _job_or_400(lambda: gcode.plot_layers_job(layers, s, req.name))
    return _download(job, _flat(layers), req.name, fmt)


@app.get("/api/calibration/plan")
def calibration_plan() -> dict[str, Any]:
    s = _settings()
    polys = gcode.calibration_polylines()
    return _summary([gcode.Layer(gcode.DEFAULT_COLOUR, polys)], s, gcode.check_job(polys, s, (gcode.CENTRE_XY,)))


@app.get("/api/calibration/export")
def calibration_export(fmt: str = "3mf") -> Response:
    s = _settings()
    job = _job_or_400(lambda: gcode.calibration_job(s))
    return _download(job, gcode.calibration_polylines(), "calibration", fmt)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
