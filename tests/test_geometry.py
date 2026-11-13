from __future__ import annotations

import pytest

from app import geometry


def test_layout_scales_flips_and_places() -> None:
    # SVG-style coordinates, Y down: y=0 is the top of the drawing.
    src = [[(0.0, 0.0), (10.0, 0.0)], [(0.0, 20.0), (10.0, 20.0)]]
    out = geometry.layout(src, width_mm=50, x_mm=100, y_mm=30)
    assert geometry.bbox(out) == pytest.approx((100, 30, 150, 130))
    assert out[0][0] == pytest.approx((100, 130))  # SVG top edge -> back of the bed
    assert out[1][0] == pytest.approx((100, 30))


def test_layout_vertical_line_uses_height() -> None:
    out = geometry.layout([[(5.0, 0.0), (5.0, 10.0)]], width_mm=40, x_mm=0, y_mm=0)
    assert geometry.bbox(out) == pytest.approx((0, 0, 0, 40))


def test_centred_origin() -> None:
    assert geometry.centred_origin(100, 50) == (78, 103)


def test_scaled_size() -> None:
    assert geometry.scaled_size([[(0, 0), (4, 2)]], 100) == pytest.approx((100, 50))


def test_simplify_removes_collinear_points_only() -> None:
    line = [(float(i), 0.0) for i in range(11)]
    assert geometry.simplify(line, 0.1) == [(0.0, 0.0), (10.0, 0.0)]
    bent = [(0.0, 0.0), (5.0, 1.0), (10.0, 0.0)]
    assert geometry.simplify(bent, 0.1) == bent


def test_clean_drops_duplicates_and_degenerate() -> None:
    out = geometry.clean([[(1, 1), (1, 1)], [(0, 0), (0, 0), (2, 0)]])
    assert out == [[(0.0, 0.0), (2.0, 0.0)]]


def test_optimise_order_reverses_strokes() -> None:
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(30.0, 0.0), (11.0, 0.0)]  # its END is nearest to a's end, so it should be reversed
    c = [(100.0, 0.0), (120.0, 0.0)]
    assert geometry.optimise_order([c, b, a], start=(0, 0)) == [a, list(reversed(b)), c]


def test_optimise_order_reduces_travel() -> None:
    polys = [[(float(x), 0.0), (float(x), 5.0)] for x in (50, 0, 40, 10, 30, 20)]
    _, before = geometry.path_lengths(polys, (0, 0))
    _, after = geometry.path_lengths(geometry.optimise_order(polys, (0, 0)), (0, 0))
    assert after < before


def test_estimate_seconds() -> None:
    # 100 mm at 600 mm/min = 10 s, no travel, 1 stroke x 2 x 5 mm at 300 mm/min = 2 s; x 1.2 margin.
    t = geometry.estimate_seconds([[(0, 0), (100, 0)]], (0, 0), 600, 6000, 300, 5)
    assert t == pytest.approx(14.4)


def test_bounds_problems() -> None:
    assert geometry.bounds_problems([(10, 10), (200, 200)], 0, 0) == []
    probs = geometry.bounds_problems([(10, 10), (250, 100)], -10, 0)  # nozzle needs X=260
    assert len(probs) == 1 and probs[0].startswith("Nozzle") and " X:" in probs[0]


def test_place_scales_flips_and_centres() -> None:
    from app.geometry import bbox, place
    src = [[(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)]]  # 20 x 10 units, Y down
    out = place(src, 100, 128, 128)
    assert bbox(out) == pytest.approx((78, 103, 178, 153))
    assert out[0][0] == pytest.approx((78, 153))  # source top-left (Y down) ends up top-left on the bed (Y up)


def test_place_rotates_about_the_centre() -> None:
    from app.geometry import bbox, place
    src = [[(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)]]
    out = place(src, 100, 128, 128, rotation_deg=90)
    assert bbox(out) == pytest.approx((103, 78, 153, 178))  # 50 wide, 100 tall, same centre
    assert out[0][1] == pytest.approx((103, 178))  # the top-right corner swings round to the top-left


def test_place_stretches_to_a_height() -> None:
    from app.geometry import bbox, place
    src = [[(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)]]
    assert bbox(place(src, 100, 128, 128, height_mm=80)) == pytest.approx((78, 88, 178, 168))
    assert bbox(place(src, 100, 128, 128, rotation_deg=90, height_mm=80)) == pytest.approx((88, 78, 168, 178))


def _covered_length(lines: list[geometry.Polyline]) -> float:
    return sum(geometry.polyline_length(p) for p in lines)


def test_hatch_fills_a_square() -> None:
    square = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    lines = geometry.hatch(square, 1.0, 0)
    assert len(lines) == 10 and all(len(p) == 2 for p in lines)
    assert _covered_length(lines) == pytest.approx(100)  # area / spacing
    ys = sorted(p[0][1] for p in lines)
    assert ys[0] == pytest.approx(0.5) and ys[-1] == pytest.approx(9.5)  # centred inside the shape
    for p in geometry.hatch(square, 0.5, 30):
        for x, y in p:
            assert -1e-9 <= x <= 10 + 1e-9 and -1e-9 <= y <= 10 + 1e-9
    assert _covered_length(geometry.hatch(square, 0.5, 30)) == pytest.approx(200, rel=0.03)


def test_hatch_angle() -> None:
    square = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    (a, b), *_ = geometry.hatch(square, 2.0, 90)
    assert a[0] == pytest.approx(b[0])  # vertical lines


def test_hatch_holes_follow_the_fill_rule() -> None:
    outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    inner_same_way = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0)]
    inner_reversed = list(reversed(inner_same_way))
    full, ring = 1000.0, 1000.0 - 160.0  # area / 0.1 mm spacing
    assert _covered_length(geometry.hatch([outer, inner_same_way], 0.1, 0, evenodd=True)) == pytest.approx(ring, rel=0.02)
    assert _covered_length(geometry.hatch([outer, inner_same_way], 0.1, 0)) == pytest.approx(full, rel=0.02)
    assert _covered_length(geometry.hatch([outer, inner_reversed], 0.1, 0)) == pytest.approx(ring, rel=0.02)


def test_hatch_rejects_zero_spacing() -> None:
    with pytest.raises(ValueError):
        geometry.hatch([[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]], 0)


def test_place_part_of_a_drawing_uses_the_whole_drawing() -> None:
    whole = [[(0.0, 0.0), (10.0, 0.0)], [(0.0, 10.0), (10.0, 10.0)]]
    assert geometry.place(whole[:1], 100, 50, 50, ref=whole) == geometry.place(whole, 100, 50, 50)[:1]
