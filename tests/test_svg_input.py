from __future__ import annotations

import math
from pathlib import Path

import pytest

from app import geometry
from app.svg_input import svg_to_polylines

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def svg(body: str) -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{body}</svg>'.encode()


def test_rect_becomes_closed_outline() -> None:
    polys = svg_to_polylines(svg('<rect x="10" y="20" width="30" height="40"/>')).polylines
    assert len(polys) == 1
    assert geometry.bbox(polys) == pytest.approx((10, 20, 40, 60))
    assert polys[0][0] == pytest.approx(polys[0][-1])


def test_circle_is_sampled_round() -> None:
    polys = svg_to_polylines(svg('<circle cx="50" cy="50" r="20"/>')).polylines
    assert geometry.bbox(polys) == pytest.approx((30, 30, 70, 70), abs=0.05)
    assert len(polys[0]) > 50
    for x, y in polys[0]:
        assert math.hypot(x - 50, y - 50) == pytest.approx(20, abs=0.01)


def test_transforms_are_applied() -> None:
    body = '<g transform="translate(10 5) scale(2)"><line x1="0" y1="0" x2="10" y2="0"/></g>'
    polys = svg_to_polylines(svg(body)).polylines
    assert len(polys) == 1
    assert polys[0][0] == pytest.approx((10, 5)) and polys[0][-1] == pytest.approx((30, 5))


def test_polygon_and_polyline() -> None:
    polys = svg_to_polylines(svg('<polygon points="0,0 10,0 10,10"/><polyline points="20,0 30,0 30,10"/>')).polylines
    assert len(polys) == 2
    assert len(polys[0]) == 4  # polygon closes back to its start
    assert len(polys[1]) == 3


def test_subpaths_split_into_separate_polylines() -> None:
    assert len(svg_to_polylines(svg('<path d="M0 0 L10 0 M20 0 L30 0"/>')).polylines) == 2


def test_text_is_skipped_with_warning() -> None:
    result = svg_to_polylines((SAMPLES / "logo.svg").read_bytes())
    assert any("text" in w for w in result.warnings)


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        svg_to_polylines(b"not an svg")
    with pytest.raises(ValueError):
        svg_to_polylines(svg(""))


@pytest.mark.parametrize("name", ["shapes.svg", "curves.svg", "logo.svg"])
def test_samples_parse(name: str) -> None:
    polys = svg_to_polylines((SAMPLES / name).read_bytes()).polylines
    assert len(polys) >= 4
    assert all(len(p) >= 2 for p in polys)


def test_fills_are_recorded() -> None:
    r = svg_to_polylines(svg(
        '<rect width="10" height="10" fill="red" stroke="blue"/>'
        '<rect x="20" width="10" height="10" fill="none" stroke="black"/>'
        '<path fill="#00ff00" fill-rule="evenodd" d="M50 0 h20 v20 h-20 Z M55 5 h5 v5 h-5 Z"/>'
    ))
    assert [(f.colour, len(f.rings), f.evenodd) for f in r.fills] == [("#ff0000", 1, False), ("#00ff00", 2, True)]
    assert r.colours == ["#0000ff", "#000000", "#00ff00", "#00ff00"]  # outlines keep the stroke colour
    assert r.fill_counts() == {"#ff0000": 1, "#00ff00": 1}


def test_fills_sample() -> None:
    r = svg_to_polylines((SAMPLES / "fills.svg").read_bytes())
    assert r.fill_counts() == {"#000000": 2, "#e53935": 1, "#1e5adc": 1}
