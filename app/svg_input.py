"""SVG -> polylines.

Output polylines are in SVG user units (px at 96 dpi), Y pointing DOWN as in the SVG.
geometry.layout() later scales them to mm and flips Y.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from svgelements import SVG, Close, Color, Image, Line, Move, Path, Shape, Text

from .geometry import Polyline

# Curves are sampled so that, once the whole drawing is scaled to its final size,
# points are about (drawing size / CURVE_STEPS) apart. 2000 steps ~ 0.1 mm at 200 mm wide.
CURVE_STEPS = 2000
MAX_POINTS_PER_CURVE = 2000
DEFAULT_COLOUR = "#000000"


@dataclass
class SvgResult:
    """Polylines in SVG user units (Y down), the colour of each one ("#rrggbb"), and warnings about skipped content."""

    polylines: list[Polyline]
    warnings: list[str] = field(default_factory=list)
    colours: list[str] = field(default_factory=list)

    def colour_counts(self) -> dict[str, int]:
        """Strokes per colour, in order of first appearance."""
        counts: dict[str, int] = {}
        for c in self.colours:
            counts[c] = counts.get(c, 0) + 1
        return counts


def _visible(c: object) -> bool:
    return isinstance(c, Color) and c.value is not None and c.alpha > 0


def shape_colour(el: Shape) -> str:
    """The pen colour for a shape: its stroke colour, else its fill colour, else black. Lower-case "#rrggbb"."""
    for c in (el.stroke, el.fill):
        if _visible(c):
            return c.hexrgb.lower()
    return DEFAULT_COLOUR


def _shape_paths(svg: SVG) -> tuple[list[tuple[Path, str]], list[str]]:
    """All drawable shapes as (Path with its transform applied, colour)."""
    paths: list[tuple[Path, str]] = []
    skipped_text = skipped_images = 0
    for el in svg.elements():
        if isinstance(el, Text):
            skipped_text += 1
        elif isinstance(el, Image):
            skipped_images += 1
        elif isinstance(el, Shape):
            path = abs(Path(el))  # abs() applies the element's transform
            if len(path) > 0:
                paths.append((path, shape_colour(el)))
    warnings = []
    if skipped_text:
        warnings.append(f"Skipped {skipped_text} text element(s): convert text to paths in your editor first.")
    if skipped_images:
        warnings.append(f"Skipped {skipped_images} embedded image(s).")
    return paths, warnings


def _path_to_polylines(path: Path, step: float) -> list[Polyline]:
    """Flatten one path into polylines; curves are sampled every ~step user units."""
    polys: list[Polyline] = []
    cur: Polyline = []
    for seg in path:
        if isinstance(seg, Move):
            if len(cur) >= 2:
                polys.append(cur)
            cur = [(seg.end.x, seg.end.y)]
            continue
        if seg.start is None or seg.end is None:
            continue
        if not cur:
            cur = [(seg.start.x, seg.start.y)]
        if isinstance(seg, (Line, Close)):
            cur.append((seg.end.x, seg.end.y))
        else:  # Arc, CubicBezier, QuadraticBezier
            length = seg.length(error=1e-4)
            n = min(MAX_POINTS_PER_CURVE, max(2, math.ceil(length / step)))
            for i in range(1, n + 1):
                p = seg.point(i / n)
                cur.append((float(p.x), float(p.y)))
    if len(cur) >= 2:
        polys.append(cur)
    return polys


def svg_to_polylines(data: bytes) -> SvgResult:
    """Parse SVG bytes and flatten every shape (paths, rects, circles, polygons...) into polylines.

    Raises ValueError if the file is not a usable SVG.
    """
    try:
        svg = SVG.parse(io.BytesIO(data), reify=True)
    except Exception as exc:  # svgelements raises a variety of parser errors
        raise ValueError(f"Could not read SVG: {exc}") from exc
    paths, warnings = _shape_paths(svg)
    boxes = [b for b in (p.bbox() for p, _ in paths) if b is not None]
    if not boxes:
        raise ValueError("The SVG contains no drawable shapes.")
    size = max(max(b[2] for b in boxes) - min(b[0] for b in boxes), max(b[3] for b in boxes) - min(b[1] for b in boxes))
    step = max(size, 1e-9) / CURVE_STEPS
    polys: list[Polyline] = []
    colours: list[str] = []
    for path, colour in paths:
        for poly in _path_to_polylines(path, step):
            polys.append(poly)
            colours.append(colour)
    if not polys:
        raise ValueError("The SVG contains no drawable shapes.")
    return SvgResult(polylines=polys, warnings=warnings, colours=colours)
