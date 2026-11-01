"""Parse generated G-code and assert every G-code safety rule."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from app import geometry
from app.gcode import MAX_COMMAND_LINE, BoundsError, Layer, calibration_job, clip_xy, clip_z, pen_start, plot_job, plot_layers_job
from app.settings import Settings
from app.svg_input import svg_to_polylines

from .gcode_parse import Cmd, parse

BED = 256.0
SAMPLES = Path(__file__).resolve().parent.parent / "samples"
HEATERS = {"M104", "M109", "M140", "M190"}
FILAMENT_CMDS = {"M620", "M621", "M622", "M623", "M701", "M702", "G92"}

SETTINGS_CASES = {
    "defaults": Settings(),
    "offset_left_front": Settings(offset_x=-32.5, offset_y=-12.0),
    "offset_right_back": Settings(offset_x=25.0, offset_y=5.5),
    "timed_pause": Settings(pause_seconds=45, z_draw=3.5, z_lift=9.0),
    "dry_run": Settings(z_draw=7.0, z_lift=12.0, offset_x=-20),
    "holder_60_pen_in_front": Settings(holder_front=60, offset_y=-45),
    "holder_60_pen_under_nozzle": Settings(holder_front=60),
}


def sample_job_polys(name: str, s: Settings, width: float = 120.0) -> list[geometry.Polyline]:
    src = svg_to_polylines((SAMPLES / name).read_bytes()).polylines
    w, h = geometry.scaled_size(src, width)
    x, y = geometry.centred_origin(w, h)
    y = max(y, s.offset_y + s.min_nozzle_y())  # keep clear of the holder's no-go zone at the front
    placed = geometry.clean(geometry.layout(src, width, x, y), 0.05)
    return geometry.optimise_order(placed, pen_start(s))


def random_polys(s: Settings, seed: int) -> list[geometry.Polyline]:
    """Random strokes anywhere the pen can legally reach."""
    rnd = random.Random(seed)
    x0, x1 = max(0, s.offset_x), min(BED, BED + s.offset_x)
    y0, y1 = max(0, s.offset_y, s.offset_y + s.min_nozzle_y()), min(BED, BED + s.offset_y)
    return [[(rnd.uniform(x0, x1), rnd.uniform(y0, y1)) for _ in range(rnd.randint(2, 6))] for _ in range(40)]


def is_pause(c: Cmd) -> bool:
    return (c.name == "M400" and c.params.get("U") == 1) or (c.name == "G4" and c.params.get("S", 0) > 0)


def assert_safe(gcode: str, s: Settings) -> None:
    cmds = parse(gcode)

    # Every command line is short (the printer ignored a pause written as one 150-character line), and every
    # pause is Bambu's bare "M400 U1" (or a timed "G4 S<n>") with nothing else on the line.
    for line in gcode.splitlines():
        if line.strip() and not line.startswith(";"):
            assert len(line) <= MAX_COMMAND_LINE, f"command line too long: {line!r}"
        if line.startswith("M400 U"):
            assert line == "M400 U1", line
    names = [c.name for c in cmds]

    # Rule 7: absolute mm, set before any move; only G0/G1 moves; never relative.
    first_move = next(i for i, c in enumerate(cmds) if c.name in {"G0", "G1", "G28"})
    assert names.index("G90") < first_move and names.index("G21") < first_move
    assert "G91" not in names
    assert not {"G2", "G3", "G5"} & set(names)

    # Rule 1: heaters only ever set to 0, and explicitly switched off before homing.
    for c in cmds:
        if c.name in HEATERS:
            assert c.params.get("S", 0) == 0, f"heater command on line {c.line_no}"
    i_home = names.index("G28")
    assert any(c.name == "M104" and c.params.get("S") == 0 for c in cmds[:i_home])
    assert any(c.name == "M140" and c.params.get("S") == 0 for c in cmds[:i_home])
    # ...and again straight after homing (the printer may warm the nozzle during G28) and at the end.
    assert [(c.name, c.params.get("S")) for c in cmds[i_home + 1:i_home + 3]] == [("M104", 0), ("M140", 0)]
    # ...then tell the printer that preparation is over, before the first pause (Bambu's start code ends like this).
    lines = gcode.splitlines()
    i_g28 = next(i for i, line in enumerate(lines) if line.startswith("G28"))
    i_wait = next(i for i, line in enumerate(lines) if line.startswith(("M400 U1", "G4 S")))
    assert "M1002 gcode_claim_action : 0" in lines[i_g28:i_wait]
    end_cmds = [c.name for c in cmds if c.name != "M73"][-6:]
    assert end_cmds[:2] == ["M104", "M140"]

    # Rule 2: no extrusion or filament handling at all.
    for c in cmds:
        assert "E" not in c.params, f"E value on line {c.line_no}"
        assert c.name not in FILAMENT_CMDS, f"{c.name} on line {c.line_no}"

    # Holder clearance: the holder is always attached, so EVERY XY move (before and after the pause)
    # keeps the nozzle at Y >= holder_front + 5 mm.
    for c in cmds:
        if c.name in {"G0", "G1"} and "Y" in c.params:
            assert c.params["Y"] >= s.min_nozzle_y(), f"holder too close to the front on line {c.line_no}"

    # Rule 3: home once, lift, go to the pen stop (X128 Y20, or further back), pause - all before any drawing.
    assert names.count("G28") == 1
    i_pause = next(i for i, c in enumerate(cmds) if i > i_home and is_pause(c))
    if s.pause_seconds > 0:
        assert cmds[i_pause].name == "G4" and cmds[i_pause].params["S"] == s.pause_seconds
    else:
        assert cmds[i_pause].name == "M400" and cmds[i_pause].params["U"] == 1
    before = [c for c in cmds[i_home + 1:i_pause] if c.name in {"G0", "G1"}]
    assert before[0].params.keys() == {"Z", "F"} and before[0].params["Z"] > s.z_lift
    assert all(c.name == "G0" for c in before), "no drawing before the pen is fitted"
    last_xy = [c for c in before if "X" in c.params][-1]
    assert (last_xy.params["X"], last_xy.params["Y"]) == clip_xy(s)

    # Pen changes: before every later pause that happens at the front (X128 Y20), the toolhead was lifted to
    # clip_z, then moved there at that height, then M400; right after the pause the pen goes back to z_lift.
    pen_change_moves: set[int] = set()
    for j in (j for j, c in enumerate(cmds) if j > i_pause and is_pause(c)):
        moves = [c for c in cmds[i_pause + 1:j] if c.name in {"G0", "G1"}]
        last_xy = [c for c in moves if "X" in c.params or "Y" in c.params][-1]
        if (last_xy.params.get("X"), last_xy.params.get("Y")) != clip_xy(s):
            continue  # e.g. the calibration park, checked by its own test
        assert cmds[j - 1].name == "M400", f"no M400 before pen-change pause on line {cmds[j].line_no}"
        assert moves[-2].params.keys() == {"Z", "F"} and moves[-2].params["Z"] == clip_z(s)
        assert last_xy is moves[-1] and last_xy.name == "G0"
        nxt = next(c for c in cmds[j + 1:] if c.name in {"G0", "G1"})
        assert nxt.name == "G0" and nxt.params.keys() == {"Z", "F"} and nxt.params["Z"] == s.z_lift
        pen_change_moves.add(id(last_xy))
    if s.pause_seconds > 0:
        assert all(c.name == "G4" for c in cmds if is_pause(c))

    # Every pause is laid out like Bambu Studio's: heaters off, layer-change notice (M73 L<n>, M991 S0 P<n-1>),
    # M400 directly before the pause, and heaters off again straight after it.
    pause_idx = [j for j, c in enumerate(cmds) if is_pause(c)]
    for n, j in enumerate(pause_idx, 1):
        before = [(c.name, c.params.get("S"), c.params.get("L"), c.params.get("P")) for c in cmds[j - 5:j]]
        assert before == [("M104", 0, None, None), ("M140", 0, None, None), ("M73", None, n, None),
                          ("M991", 0, None, n - 1), ("M400", None, None, None)], f"pause block wrong on line {cmds[j].line_no}"
        after = [(c.name, c.params.get("S")) for c in cmds[j + 1:j + 3]]
        assert after == [("M104", 0), ("M140", 0)], f"heaters not off after the pause on line {cmds[j].line_no}"
    assert f"; total layer number: {len(pause_idx)}" in gcode

    # Pen fitting and pen changes happen at the pen-setting height: 10 mm cube + 6 mm pen.
    assert clip_z(s) == 16

    # Rules 4 and 5: simulate position after the pen is fitted.
    (x, y), z = clip_xy(s), None
    after = [c for c in cmds[i_pause + 1:] if c.name in {"G0", "G1"}]
    xy_g0 = [c for c in after if c.name == "G0" and ("X" in c.params or "Y" in c.params)]
    for c in after:
        x, y, z = c.params.get("X", x), c.params.get("Y", y), c.params.get("Z", z)
        assert z is not None and z >= s.z_draw, f"Z below z_draw on line {c.line_no}"
        has_xy = "X" in c.params or "Y" in c.params
        if not has_xy:
            # Z-only moves: pen down is G1 to z_draw, pen up is G0 to z_lift (or higher at the end).
            if c.name == "G1":
                assert z == s.z_draw
            else:
                assert z >= s.z_lift
            continue
        for px, py, who in ((x, y, "nozzle"), (x + s.offset_x, y + s.offset_y, "pen")):
            assert 0 <= px <= BED and 0 <= py <= BED, f"{who} off bed at line {c.line_no}: {px}, {py}"
        if c.name == "G1":
            assert "Z" not in c.params and z == s.z_draw, f"drawing move not at z_draw on line {c.line_no}"
        else:
            if c is xy_g0[-1]:
                expected_z = s.z_lift + 30
            elif id(c) in pen_change_moves:
                expected_z = clip_z(s)
            else:
                expected_z = s.z_lift
            assert z == expected_z, f"travel not at z_lift on line {c.line_no}"
    # Before the pause nothing goes below z_draw either.
    assert all(c.params.get("Z", s.z_draw) >= s.z_draw for c in cmds)

    # Rule 6: lift 30 mm, park at X128 Y250, M400, M18 - in that order, at the very end.
    tail = [c for c in cmds if c.name != "M73"][-4:]
    assert [c.name for c in tail] == ["G0", "G0", "M400", "M18"]
    z_before_lift = [c.params["Z"] for c in after[:-2] if "Z" in c.params][-1]
    assert tail[0].params["Z"] == pytest.approx(z_before_lift + 30)
    assert (tail[1].params["X"], tail[1].params["Y"]) == (128, 250)


@pytest.mark.parametrize("case", SETTINGS_CASES)
@pytest.mark.parametrize("sample", ["shapes.svg", "curves.svg", "logo.svg"])
def test_sample_jobs_are_safe(sample: str, case: str) -> None:
    s = SETTINGS_CASES[case]
    polys = sample_job_polys(sample, s)
    assert_safe(plot_job(polys, s, sample).gcode, s)


@pytest.mark.parametrize("case", SETTINGS_CASES)
def test_calibration_job_is_safe(case: str) -> None:
    s = SETTINGS_CASES[case]
    gcode = calibration_job(s).gcode
    assert_safe(gcode, s)
    cmds = parse(gcode)
    # A second pause, with the NOZZLE parked over bed centre at z_lift.
    pauses = [i for i, c in enumerate(cmds) if is_pause(c)]
    assert len(pauses) == 2
    park = [c for c in cmds[:pauses[1]] if "X" in c.params][-1]
    assert (park.params["X"], park.params["Y"]) == (128, 128)
    assert [c.params["Z"] for c in cmds[:pauses[1]] if "Z" in c.params][-1] == s.z_lift


def test_calibration_cross_is_where_the_pen_should_be() -> None:
    s = Settings(offset_x=-30, offset_y=4)
    x = y = z = 0.0
    drawn: list[tuple[float, float]] = []  # pen positions while the pen is down
    for c in parse(calibration_job(s).gcode):
        if c.name in {"G0", "G1"}:
            x, y, z = c.params.get("X", x), c.params.get("Y", y), c.params.get("Z", z)
            if z == s.z_draw:
                drawn.append((x + s.offset_x, y + s.offset_y))
    assert geometry.bbox([drawn]) == pytest.approx((113, 113, 143, 143))


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("case", ["defaults", "offset_left_front", "offset_right_back"])
def test_random_jobs_are_safe(case: str, seed: int) -> None:
    s = SETTINGS_CASES[case]
    assert_safe(plot_job(random_polys(s, seed), s).gcode, s)


def test_refuses_pen_off_bed() -> None:
    with pytest.raises(BoundsError) as exc:
        plot_job([[(-1.0, 10.0), (50.0, 10.0)]], Settings())
    assert any("Pen goes outside the bed in X" in p for p in exc.value.problems)


def test_refuses_nozzle_off_bed() -> None:
    # With a -30 mm offset, pen X=250 needs the nozzle at X=280.
    with pytest.raises(BoundsError) as exc:
        plot_job([[(10.0, 100.0), (250.0, 100.0)]], Settings(offset_x=-30))
    assert any("Nozzle goes outside the bed in X" in p for p in exc.value.problems)


def test_refuses_when_park_puts_pen_off_bed() -> None:
    with pytest.raises(BoundsError) as exc:
        plot_job([[(100.0, 100.0), (120.0, 100.0)]], Settings(offset_y=10))
    assert any(p.startswith("End park") for p in exc.value.problems)


def test_refuses_invalid_settings() -> None:
    with pytest.raises(BoundsError):
        plot_job([[(100.0, 100.0), (120.0, 100.0)]], Settings(z_draw=0.0))
    with pytest.raises(BoundsError):
        plot_job([[(100.0, 100.0), (120.0, 100.0)]], Settings(z_draw=5, z_lift=4))


def test_refuses_empty_job() -> None:
    with pytest.raises(BoundsError):
        plot_job([], Settings())


def colour_layers(s: Settings, pens: list[list[str]] | None = None) -> list[Layer]:
    """samples/colours.svg laid out 120 mm wide in the middle of the bed, one layer per pen."""
    src = svg_to_polylines((SAMPLES / "colours.svg").read_bytes())
    w, h = geometry.scaled_size(src.polylines, 120)
    placed = geometry.layout(src.polylines, 120, *geometry.centred_origin(w, h))
    pens = pens if pens is not None else [[c] for c in src.colour_counts()]
    return [
        Layer(group[0], geometry.optimise_order([p for p, c in zip(placed, src.colours) if c in group], pen_start(s)))
        for group in pens
    ]


MULTI_PEN_CASES = dict(SETTINGS_CASES, highest_lift=Settings(z_draw=13, z_lift=15))


@pytest.mark.parametrize("case", MULTI_PEN_CASES)
def test_multi_pen_jobs_are_safe(case: str) -> None:
    s = MULTI_PEN_CASES[case]
    layers = colour_layers(s)
    assert [layer.colour for layer in layers] == ["#000000", "#ff0000", "#e53935", "#1e5adc"]
    gcode = plot_layers_job(layers, s, "colours").gcode
    assert_safe(gcode, s)
    cmds = parse(gcode)
    pauses = [i for i, c in enumerate(cmds) if is_pause(c)]
    assert len(pauses) == len(layers)  # first pen + one per change
    assert gcode.count("; PEN_CHANGE ") == len(layers) - 1
    # Each pen draws exactly its own strokes, between its pause and the next one.
    for k, layer in enumerate(layers):
        end = pauses[k + 1] if k + 1 < len(pauses) else len(cmds)
        pen_downs = [c for c in cmds[pauses[k]:end] if c.name == "G1" and c.params.keys() == {"Z", "F"}]
        assert len(pen_downs) == len(layer.polylines)


def test_merged_and_skipped_colours() -> None:
    s = Settings()
    layers = colour_layers(s, [["#ff0000", "#e53935"], ["#000000"]])  # the two reds on one pen, blue skipped
    job = plot_layers_job(layers, s)
    assert_safe(job.gcode, s)
    assert job.gcode.count("; PEN_CHANGE ") == 1
    assert "swap to pen 2 of 2 (#000000)" in job.gcode
    assert "fit pen 1 (#ff0000): stand the 10 mm cube under the pen" in job.gcode and "REMOVE the cube" in job.gcode


def test_single_pen_job_has_no_pen_change() -> None:
    gcode = plot_layers_job([Layer("#000000", [[(100.0, 100.0), (120.0, 100.0)]]), Layer("#ff0000", [])], Settings()).gcode
    assert "; PEN_CHANGE" not in gcode and "PAUSE: fit the pen: stand the 10 mm cube" in gcode


def test_pen_stop_moves_back_so_the_pen_is_over_the_bed() -> None:
    # Pen 25 mm in front of the nozzle: at nozzle Y20 the pen would be at Y-5, so the stop moves to Y25.
    s = Settings(offset_y=-25, holder_front=0)
    assert clip_xy(s) == (128, 25)
    layers = [Layer("#000000", [[(100.0, 100.0), (120.0, 100.0)]]), Layer("#ff0000", [[(100.0, 110.0), (120.0, 110.0)]])]
    assert_safe(plot_layers_job(layers, s).gcode, s)


def test_pen_stop_moves_back_for_the_holder() -> None:
    s = Settings(holder_front=60)
    assert s.min_nozzle_y() == 65 and clip_xy(s) == (128, 65)
    assert clip_xy(Settings(holder_front=0)) == (128, 20)  # no holder reach: the original spot
    assert clip_xy(Settings()) == (128, 65)  # the default is the user's 60 mm holder


def test_refuses_drawing_too_close_to_the_front_for_the_holder() -> None:
    s = Settings(holder_front=60)  # nozzle must stay at Y >= 65; pen is under the nozzle
    with pytest.raises(BoundsError) as exc:
        plot_job([[(100.0, 40.0), (150.0, 40.0)]], s)
    msg = next(p for p in exc.value.problems if p.startswith("Holder would hit the front"))
    assert "nozzle at Y40" in msg and "Y65 or more" in msg and "by at least 25 mm" in msg
    assert_safe(plot_job([[(100.0, 65.0), (150.0, 70.0)]], s).gcode, s)


def test_refuses_calibration_if_holder_reach_is_huge() -> None:
    with pytest.raises(BoundsError):
        calibration_job(Settings(holder_front=140))  # nozzle must stay at Y >= 145, cross is at Y113..143
