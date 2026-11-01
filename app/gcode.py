"""Polylines (pen coordinates, mm) -> P1S G-code, plus the offset calibration job.

See "Safety" in README.md; tests/test_gcode_safety.py enforces them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import BED_SIZE_MM, Point, Polyline, bounds_problems, estimate_seconds, polyline_length
from .settings import PEN_LENGTH_MM, PEN_SET_Z_MM, SETTING_CUBE_MM, Settings

CLIP_NOZZLE_XY: Point = (128.0, 20.0)   # nozzle position for fitting/changing the pen, unless moved back (clip_xy)
PARK_NOZZLE_XY: Point = (128.0, 250.0)  # nozzle position at the end of the job
CENTRE_XY: Point = (BED_SIZE_MM / 2, BED_SIZE_MM / 2)
END_LIFT_MM = 30.0      # extra lift at the end, mm
HOMING_OVERHEAD_S = 90.0  # homing + start/end moves, seconds (rough)
PEN_CHANGE_OVERHEAD_S = 20.0  # lift, trip to the front and back per pen change, seconds (rough; the wait is extra)
PEN_FITTED_MARKER = "; PEN_FITTED"
PEN_CHANGE_MARKER = "; PEN_CHANGE"
DEFAULT_COLOUR = "#000000"
BAMBU_VERSION = "02.08.02.61"


class BoundsError(ValueError):
    """Raised when a job would move the pen or nozzle off the bed, or settings are invalid."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(" ".join(problems))


@dataclass
class Layer:
    """Strokes drawn with one pen: colour ("#rrggbb", for messages and preview) and polylines (pen coordinates, mm)."""

    colour: str
    polylines: list[Polyline] = field(default_factory=list)


@dataclass
class Job:
    """Generated G-code and its time estimate (seconds)."""

    gcode: str
    estimated_seconds: float
    strokes: int


def _f(v: float) -> str:
    """Format a number for G-code: up to 3 decimals, no trailing zeros."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def pen_to_nozzle(p: Point, s: Settings) -> Point:
    """Nozzle position (mm) that puts the pen at p."""
    return p[0] - s.offset_x, p[1] - s.offset_y


def nozzle_to_pen(p: Point, s: Settings) -> Point:
    """Pen position (mm) when the nozzle is at p."""
    return p[0] + s.offset_x, p[1] + s.offset_y


def clip_xy(s: Settings) -> Point:
    """Nozzle position (mm) for fitting or changing the pen: X128 at the front, moved back as far as needed
    so the holder clears the front (Y >= min_nozzle_y) and the pen tip is over the bed (pen Y >= 0)."""
    x, y = CLIP_NOZZLE_XY
    return x, max(y, s.min_nozzle_y(), -s.offset_y)


def pen_start(s: Settings) -> Point:
    """Where the pen is right after it has been clipped on (mm)."""
    return nozzle_to_pen(clip_xy(s), s)


def clip_z(s: Settings) -> float:
    """Nozzle Z (mm) while fitting or changing a pen: the user rests the pen tip on a SETTING_CUBE_MM cube,
    which puts it exactly PEN_LENGTH_MM below the nozzle."""
    return PEN_SET_Z_MM


def job_seconds(polys: list[Polyline], s: Settings) -> float:
    """Estimated total job time in seconds, including homing and a timed pause if set."""
    return layers_seconds([Layer(DEFAULT_COLOUR, polys)], s)


def layers_seconds(layers: list[Layer], s: Settings) -> float:
    """Estimated time in seconds for a multi-pen job; every pen starts at the front, where it was fitted."""
    changes = max(0, len(layers) - 1)
    motion = sum(
        estimate_seconds(layer.polylines, pen_start(s), s.draw_speed, s.travel_speed, s.z_speed, s.z_lift - s.z_draw)
        for layer in layers
    )
    return motion + HOMING_OVERHEAD_S + s.pause_seconds * (1 + changes) + PEN_CHANGE_OVERHEAD_S * changes


def check_job(polys: list[Polyline], s: Settings, extra_nozzle_xy: tuple[Point, ...] = (), pen_changes: int = 0) -> list[str]:
    """All reasons this job must not be exported (settings problems and safety rule 4). Empty = OK.

    pen_changes > 0 also checks the pen-change spot at the front, where the pen is still fitted.
    """
    problems = s.validate()
    if not polys:
        problems.append("Nothing to draw.")
    problems += bounds_problems([p for poly in polys for p in poly], s.offset_x, s.offset_y)
    stops = [("Pen fitting", clip_xy(s)), ("End park", PARK_NOZZLE_XY)]
    stops += [("Calibration park", p) for p in extra_nozzle_xy]
    problems += _front_problems(polys, s)
    for label, nozzle in stops:
        for msg in bounds_problems([nozzle_to_pen(nozzle, s)], s.offset_x, s.offset_y):
            problems.append(f"{label} (nozzle X{_f(nozzle[0])} Y{_f(nozzle[1])}): {msg}")
    return problems


def _front_problems(polys: list[Polyline], s: Settings) -> list[str]:
    """Holder clearance: no drawing point may need the nozzle closer to the front than min_nozzle_y."""
    if not polys or s.min_nozzle_y() <= 0:
        return []
    lowest = min(pen_to_nozzle(p, s)[1] for poly in polys for p in poly)
    if lowest >= s.min_nozzle_y():
        return []
    return [
        f"Holder would hit the front: the drawing needs the nozzle at Y{_f(lowest)}, but with the holder reaching "
        f"{_f(s.holder_front)} mm in front it must stay at Y{_f(s.min_nozzle_y())} or more. "
        f"Move the drawing back (up) by at least {_f(s.min_nozzle_y() - lowest)} mm."
    ]


MAX_COMMAND_LINE = 48  # printer firmware reads lines into a small buffer: long command lines may be dropped


def _short_lines(lines: list[str]) -> list[str]:
    """Move the note of any long command line onto its own comment line just above, so every command
    line stays short (comment-only lines may be long; Bambu's own files have very long ones)."""
    out: list[str] = []
    for line in lines:
        code, sep, note = line.partition(";")
        if code.strip() and sep and len(line) > MAX_COMMAND_LINE:
            out += [f"; {note.strip()}", code.rstrip()]
        else:
            out.append(line)
    return out


HEATERS_OFF = ["M104 S0 ; nozzle heater off", "M140 S0 ; bed heater off"]


def _pause(s: Settings, message: str, layer: int) -> list[str]:
    """Pause for the user, laid out like a Bambu Studio pause: heaters off, a layer-change notice
    (M73 L / M991, as Bambu's own files have before every pause), M400, then the pause itself
    straight after it, and heaters off again on resume. layer counts the pauses from 1."""
    if s.pause_seconds > 0:
        wait = f"G4 S{_f(s.pause_seconds)} ; PAUSE {_f(s.pause_seconds)} s: {message}"
    else:
        wait = f"M400 U1 ; PAUSE: {message}, then press Resume"
    return [
        *HEATERS_OFF,
        f"; layer num/total_layer_count: {layer}",
        f"M73 L{layer}",
        f"M991 S0 P{layer - 1} ; notify layer change",
        "M400",
        wait,
        *HEATERS_OFF,
    ]


def _pen_setting(what: str) -> str:
    """Pause message for fitting a pen with the setting cube."""
    return (f"{what}: stand the {_f(SETTING_CUBE_MM)} mm cube under the pen, rest the pen tip on it, tighten, "
            "then REMOVE the cube")


def _header(title: str, seconds: float, layers: int) -> list[str]:
    m, sec = divmod(int(round(seconds)), 60)
    return [
        "; HEADER_BLOCK_START",
        f"; BambuStudio {BAMBU_VERSION}",
        f"; model printing time: {m}m {sec}s; total estimated time: {m}m {sec}s",
        f"; total layer number: {layers}",
        "; total filament length [mm] : 0.00",
        "; total filament volume [cm^3] : 0.00",
        "; total filament weight [g] : 0.00",
        f"; max_z_height: {PEN_SET_Z_MM:.2f}",
        "; HEADER_BLOCK_END",
        "",
        f"; P1S pen plotter job: {title}",
        "; No heating, no extrusion. Pen must NOT be fitted until the first pause.",
        "; EXECUTABLE_BLOCK_START",
    ]


def _start(s: Settings, first_colour: str = "") -> list[str]:
    x, y = clip_xy(s)
    what = _pen_setting(f"fit pen 1 ({first_colour})" if first_colour else "fit the pen")
    return [
        "G21 ; millimetres",
        "G90 ; absolute coordinates",
        "M104 S0 ; nozzle heater off",
        "M140 S0 ; bed heater off",
        "M73 P0",
        "G28 ; home all axes (pen NOT fitted)",
        "M104 S0 ; nozzle heater off again: the printer may warm the nozzle while homing",
        "M140 S0 ; bed heater off again",
        "M1002 gcode_claim_action : 0 ; tell the printer preparation is over (it may ignore pauses while 'preparing')",
        "; MACHINE_START_GCODE_END",
        f"G0 Z{_f(clip_z(s))} F{_f(s.z_speed)} ; pen-setting height: {_f(SETTING_CUBE_MM)} mm cube + {_f(PEN_LENGTH_MM)} mm pen",
        f"G0 X{_f(x)} Y{_f(y)} F{_f(s.travel_speed)} ; toolhead to the front",
        *_pause(s, what, 1),
        PEN_FITTED_MARKER,
        f"G0 Z{_f(s.z_lift)} F{_f(s.z_speed)} ; pen up",
    ]


def _pen_change(s: Settings, number: int, total: int, colour: str) -> list[str]:
    """Lift high, bring the toolhead to the front and pause so the user can swap pens."""
    x, y = clip_xy(s)
    return [
        f"{PEN_CHANGE_MARKER} {number}/{total}: {colour}",
        f"G0 Z{_f(clip_z(s))} F{_f(s.z_speed)} ; lift for the pen change",
        f"G0 X{_f(x)} Y{_f(y)} F{_f(s.travel_speed)} ; toolhead to the front",
        *_pause(s, _pen_setting(f"swap to pen {number} of {total} ({colour})"), number),
        PEN_FITTED_MARKER,
        f"G0 Z{_f(s.z_lift)} F{_f(s.z_speed)} ; pen up",
    ]


@dataclass
class _Progress:
    """Running totals for M73 progress lines across all pens."""

    total_s: float
    total_len: float
    total_strokes: int
    done_len: float = 0.0
    done_strokes: int = 0
    last_pct: int = 0


def _draw(polys: list[Polyline], s: Settings, prog: _Progress) -> list[str]:
    out: list[str] = []
    for poly in polys:
        prog.done_strokes += 1
        nx, ny = pen_to_nozzle(poly[0], s)
        out.append(f"; stroke {prog.done_strokes}/{prog.total_strokes}")
        out.append(f"G0 X{_f(nx)} Y{_f(ny)} F{_f(s.travel_speed)}")
        out.append(f"G1 Z{_f(s.z_draw)} F{_f(s.z_speed)} ; pen down")
        for j, p in enumerate(poly[1:]):
            nx, ny = pen_to_nozzle(p, s)
            out.append(f"G1 X{_f(nx)} Y{_f(ny)}" + (f" F{_f(s.draw_speed)}" if j == 0 else ""))
        out.append(f"G0 Z{_f(s.z_lift)} F{_f(s.z_speed)} ; pen up")
        prog.done_len += polyline_length(poly)
        pct = min(99, int(100 * prog.done_len / prog.total_len))
        if pct != prog.last_pct:
            remaining_min = math.ceil(prog.total_s * (1 - prog.done_len / prog.total_len) / 60)
            out.append(f"M73 P{pct} R{remaining_min}")
            prog.last_pct = pct
    return out


def _end(s: Settings) -> list[str]:
    x, y = PARK_NOZZLE_XY
    return [
        "M104 S0 ; nozzle heater off",
        "M140 S0 ; bed heater off",
        f"G0 Z{_f(s.z_lift + END_LIFT_MM)} F{_f(s.z_speed)} ; lift {_f(END_LIFT_MM)} mm",
        f"G0 X{_f(x)} Y{_f(y)} F{_f(s.travel_speed)} ; park",
        "M73 P100 R0",
        "M400",
        "M18 ; motors off",
        "; EXECUTABLE_BLOCK_END",
        "",
    ]


def _build(layers: list[Layer], s: Settings, title: str, after_draw: list[str], extra_nozzle_xy: tuple[Point, ...]) -> Job:
    layers = [layer for layer in layers if layer.polylines]
    polys = [p for layer in layers for p in layer.polylines]
    problems = check_job(polys, s, extra_nozzle_xy, pen_changes=max(0, len(layers) - 1))
    if problems:
        raise BoundsError(problems)
    seconds = layers_seconds(layers, s)
    prog = _Progress(seconds, sum(polyline_length(p) for p in polys) or 1.0, len(polys))
    notes = [f"; pen width: {_f(s.pen_width)} mm", f"; pen length below nozzle: {_f(s.pen_length)} mm"]
    if len(layers) > 1:
        notes += [f"; pen {i}: {layer.colour}, {len(layer.polylines)} strokes" for i, layer in enumerate(layers, 1)]
    body: list[str] = []
    for i, layer in enumerate(layers, 1):
        if i > 1:
            body += _pen_change(s, i, len(layers), layer.colour)
        body += _draw(layer.polylines, s, prog)
    steps = _start(s, layers[0].colour if len(layers) > 1 else "") + body + after_draw + _end(s)
    pauses = sum(1 for line in steps if line.startswith("M991 S0"))
    lines = _short_lines(_header(title, seconds, pauses) + notes + steps)
    return Job(gcode="\n".join(lines), estimated_seconds=seconds, strokes=len(polys))


def plot_job(polys: list[Polyline], s: Settings, title: str = "drawing") -> Job:
    """G-code that draws polys (pen coordinates, mm, already ordered) with one pen. Raises BoundsError if unsafe."""
    return _build([Layer(DEFAULT_COLOUR, polys)], s, title, [], ())


def plot_layers_job(layers: list[Layer], s: Settings, title: str = "drawing") -> Job:
    """G-code that draws each layer with its own pen, pausing at the front to swap pens in between.

    Each layer's polylines are in pen coordinates (mm) and already ordered. Empty layers are skipped.
    Raises BoundsError if unsafe.
    """
    return _build(layers, s, title, [], ())


def calibration_polylines(centre: Point = CENTRE_XY, cross_mm: float = 30.0, circle_mm: float = 10.0) -> list[Polyline]:
    """A cross (cross_mm long arms in total) and a circle (circle_mm diameter) centred on centre, mm."""
    cx, cy = centre
    h = cross_mm / 2
    r = circle_mm / 2
    circle = [(cx + r * math.cos(2 * math.pi * k / 72), cy + r * math.sin(2 * math.pi * k / 72)) for k in range(73)]
    return [[(cx - h, cy), (cx + h, cy)], [(cx, cy - h), (cx, cy + h)], circle]


def calibration_job(s: Settings) -> Job:
    """Draw the calibration cross where the pen should be at bed centre, then park the NOZZLE over bed centre and pause.

    The user measures (cross centre - nozzle tip) in X and Y and ADDS it to offset_x / offset_y.
    """
    cx, cy = CENTRE_XY
    after = [
        "; calibration: park the NOZZLE over bed centre at pen-up height",
        f"G0 X{_f(cx)} Y{_f(cy)} F{_f(s.travel_speed)}",
        *_pause(s, "measure cross centre minus nozzle tip (X and Y) and ADD it to the offsets", 2),
    ]
    return _build([Layer(DEFAULT_COLOUR, calibration_polylines())], s, "calibration", after, (CENTRE_XY,))
