"""Pure geometry helpers for polylines.

Unless stated otherwise, coordinates are bed millimetres in PEN coordinates
(origin front-left, +X right, +Y towards the back).
"""
from __future__ import annotations

import math

import numpy as np

Point = tuple[float, float]
Polyline = list[Point]

BED_SIZE_MM = 256.0


def bbox(polys: list[Polyline]) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) over all points. Raises ValueError if there are none."""
    pts = [p for poly in polys for p in poly]
    if not pts:
        raise ValueError("Drawing contains no points.")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _scale_for_width(polys: list[Polyline], width_mm: float) -> float:
    """Scale factor (mm per source unit) that makes the drawing width_mm wide."""
    min_x, min_y, max_x, max_y = bbox(polys)
    w, h = max_x - min_x, max_y - min_y
    if w > 0:
        return width_mm / w
    if h > 0:  # a purely vertical drawing: use width as the height instead
        return width_mm / h
    raise ValueError("Drawing has zero size.")


def scaled_size(polys: list[Polyline], width_mm: float) -> tuple[float, float]:
    """Width and height (mm) the drawing will have once scaled to width_mm."""
    min_x, min_y, max_x, max_y = bbox(polys)
    s = _scale_for_width(polys, width_mm)
    return (max_x - min_x) * s, (max_y - min_y) * s


def layout(polys: list[Polyline], width_mm: float, x_mm: float, y_mm: float, flip_y: bool = True) -> list[Polyline]:
    """Scale source polylines to width_mm, optionally flip Y and place the bottom-left corner at (x_mm, y_mm).

    Source coordinates are in any unit; SVG/image sources are Y-down, so flip_y defaults to True.
    """
    min_x, min_y, max_x, max_y = bbox(polys)
    s = _scale_for_width(polys, width_mm)
    if flip_y:
        return [[(x_mm + (x - min_x) * s, y_mm + (max_y - y) * s) for x, y in poly] for poly in polys]
    return [[(x_mm + (x - min_x) * s, y_mm + (y - min_y) * s) for x, y in poly] for poly in polys]


def place(
    polys: list[Polyline], width_mm: float, cx_mm: float, cy_mm: float, rotation_deg: float = 0.0,
    flip_y: bool = True, height_mm: float | None = None,
) -> list[Polyline]:
    """Scale source polylines to width_mm (measured before rotating), optionally flip Y, rotate rotation_deg
    anticlockwise about the drawing's centre, and put that centre at (cx_mm, cy_mm).

    height_mm stretches the drawing to that height (before rotating); None keeps its proportions.
    Source coordinates are in any unit; SVG/image sources are Y-down, so flip_y defaults to True.
    """
    min_x, min_y, max_x, max_y = bbox(polys)
    s = _scale_for_width(polys, width_mm)
    sy = height_mm / (max_y - min_y) if height_mm is not None and max_y > min_y else s
    mx, my = (min_x + max_x) / 2, (min_y + max_y) / 2
    a = math.radians(rotation_deg)
    c, sn = math.cos(a), math.sin(a)
    sign = -1.0 if flip_y else 1.0
    out: list[Polyline] = []
    for poly in polys:
        placed: Polyline = []
        for x, y in poly:
            u, v = (x - mx) * s, sign * (y - my) * sy
            placed.append((cx_mm + u * c - v * sn, cy_mm + u * sn + v * c))
        out.append(placed)
    return out


def centred_origin(width_mm: float, height_mm: float, bed_mm: float = BED_SIZE_MM) -> tuple[float, float]:
    """Bottom-left position (mm) that centres a width x height drawing on the bed."""
    return (bed_mm - width_mm) / 2, (bed_mm - height_mm) / 2


def _dp_keep(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker: boolean mask of points to keep."""
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = pts[i], pts[j]
        seg = b - a
        seg_len = math.hypot(*seg)
        mid = pts[i + 1:j]
        if seg_len == 0:
            d = np.hypot(*(mid - a).T)
        else:
            d = np.abs(seg[0] * (mid[:, 1] - a[1]) - seg[1] * (mid[:, 0] - a[0])) / seg_len
        k = int(np.argmax(d))
        if d[k] > tol:
            idx = i + 1 + k
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return keep


def simplify(poly: Polyline, tol_mm: float) -> Polyline:
    """Douglas-Peucker simplification; no point moves more than tol_mm (mm)."""
    if len(poly) < 3 or tol_mm <= 0:
        return list(poly)
    pts = np.asarray(poly, dtype=float)
    return [(float(x), float(y)) for x, y in pts[_dp_keep(pts, tol_mm)]]


def clean(polys: list[Polyline], tol_mm: float = 0.0) -> list[Polyline]:
    """Drop repeated points, optionally simplify, and drop polylines with fewer than 2 distinct points."""
    out: list[Polyline] = []
    for poly in polys:
        dedup: Polyline = []
        for p in poly:
            if not dedup or p != dedup[-1]:
                dedup.append((float(p[0]), float(p[1])))
        if tol_mm > 0:
            dedup = simplify(dedup, tol_mm)
        if len(dedup) >= 2:
            out.append(dedup)
    return out


def optimise_order(polys: list[Polyline], start: Point = (0.0, 0.0)) -> list[Polyline]:
    """Greedy nearest-neighbour ordering. Each stroke may be reversed so its nearest end is drawn first."""
    n = len(polys)
    if n == 0:
        return []
    starts = np.array([p[0] for p in polys], dtype=float)
    ends = np.array([p[-1] for p in polys], dtype=float)
    used = np.zeros(n, dtype=bool)
    cur = np.asarray(start, dtype=float)
    order: list[Polyline] = []
    for _ in range(n):
        d_start = np.hypot(*(starts - cur).T)
        d_end = np.hypot(*(ends - cur).T)
        d_start[used] = np.inf
        d_end[used] = np.inf
        i_s, i_e = int(np.argmin(d_start)), int(np.argmin(d_end))
        if d_end[i_e] < d_start[i_s]:
            poly = list(reversed(polys[i_e]))
            used[i_e] = True
        else:
            poly = list(polys[i_s])
            used[i_s] = True
        order.append(poly)
        cur = np.asarray(poly[-1], dtype=float)
    return order


def polyline_length(poly: Polyline) -> float:
    """Length of a polyline in mm."""
    return sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))


def path_lengths(polys: list[Polyline], start: Point) -> tuple[float, float]:
    """(drawing mm, pen-up travel mm) when plotting polys in order, starting at start."""
    draw = sum(polyline_length(p) for p in polys)
    travel = 0.0
    cur = start
    for p in polys:
        travel += math.dist(cur, p[0])
        cur = p[-1]
    return draw, travel


def estimate_seconds(
    polys: list[Polyline],
    start: Point,
    draw_speed: float,
    travel_speed: float,
    z_speed: float,
    z_travel_mm: float,
    overhead_s: float = 0.0,
) -> float:
    """Rough job time in seconds. Speeds in mm/min; z_travel_mm is the pen lift height.

    Acceleration is not modelled, so a 20 % margin is added to motion time.
    """
    draw, travel = path_lengths(polys, start)
    motion = draw / draw_speed + travel / travel_speed + len(polys) * 2 * z_travel_mm / z_speed
    return motion * 60 * 1.2 + overhead_s


def _range_problem(label: str, axis: str, lo: float, hi: float, bed_mm: float) -> str | None:
    if lo >= 0 and hi <= bed_mm:
        return None
    return f"{label} goes outside the bed in {axis}: {lo:.1f} to {hi:.1f} mm (must stay within 0-{bed_mm:g} mm)."


def bounds_problems(
    pen_points: list[Point], offset_x: float, offset_y: float, bed_mm: float = BED_SIZE_MM
) -> list[str]:
    """Check that both the pen and the nozzle stay on the bed for every given pen position (mm).

    The nozzle is at (x - offset_x, y - offset_y). Returns human-readable problems; empty means OK.
    """
    if not pen_points:
        return []
    pts = np.asarray(pen_points, dtype=float)
    problems: list[str] = []
    for label, shift in (("Pen", (0.0, 0.0)), ("Nozzle", (offset_x, offset_y))):
        moved = pts - np.asarray(shift)
        for axis, col in (("X", 0), ("Y", 1)):
            msg = _range_problem(label, axis, float(moved[:, col].min()), float(moved[:, col].max()), bed_mm)
            if msg:
                problems.append(msg)
    return problems
