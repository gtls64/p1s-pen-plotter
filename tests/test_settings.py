from __future__ import annotations

from pathlib import Path

import pytest

from app.gcode import calibration_job
from app.settings import PEN_WIDTH_PRESETS_MM, Settings, load_settings, save_settings


def test_defaults_are_valid() -> None:
    assert Settings().validate() == []
    assert Settings().pen_width == 0.4


@pytest.mark.parametrize("width", PEN_WIDTH_PRESETS_MM)
def test_pen_width_presets_are_valid(width: float) -> None:
    assert Settings(pen_width=width).validate() == []


@pytest.mark.parametrize("width", [0, -0.3, 0.01, 6])
def test_pen_width_out_of_range(width: float) -> None:
    assert any("pen_width" in p for p in Settings(pen_width=width).validate())


def test_roundtrip_and_old_files_without_pen_width(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(Settings(pen_width=0.8, offset_x=-30), path)
    assert load_settings(path) == Settings(pen_width=0.8, offset_x=-30)
    path.write_text('{"offset_x": -12}', encoding="utf-8")  # saved before pen_width existed
    assert load_settings(path).pen_width == 0.4


def test_pen_width_noted_in_gcode() -> None:
    assert "; pen width: 0.5 mm" in calibration_job(Settings(pen_width=0.5)).gcode


def test_pen_length_is_fixed_and_press_depth() -> None:
    s = Settings()
    assert s.pen_length == 6.0  # set with the 10 mm cube while the nozzle waits at Z16
    assert s.press_depth() == 1.0  # z_draw 5 with the 6 mm pen: spring pushed 1 mm
    assert Settings(z_draw=10, z_lift=12).press_depth() == -4  # dry run: tip 4 mm in the air


def test_pen_up_must_clear_the_paper() -> None:
    problems = Settings(z_draw=5, z_lift=6.5).validate()
    assert any("z_lift must be at least pen_length" in p for p in problems)
    assert Settings(z_draw=5, z_lift=7).validate() == []


def test_pen_up_stays_below_the_pen_setting_height() -> None:
    assert any("pen-setting height of Z16" in p for p in Settings(z_draw=10, z_lift=15.5).validate())
    assert Settings(z_draw=10, z_lift=15).validate() == []


def test_old_files_with_a_pen_length_are_still_read(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"z_draw": 5, "z_lift": 9, "pen_width": 0.2, "pen_length": 3}', encoding="utf-8")
    s = load_settings(path)
    assert s.pen_length == 6.0 and s.pen_width == 0.2


def test_pen_length_noted_in_gcode() -> None:
    assert "; pen length below nozzle: 6 mm" in calibration_job(Settings()).gcode


def test_holder_front() -> None:
    assert Settings(holder_front=0).min_nozzle_y() == 0  # no holder reach
    assert Settings().min_nozzle_y() == 65  # default: the user's 60 mm holder
    assert Settings(holder_front=60).min_nozzle_y() == 65
    assert any("holder_front" in p for p in Settings(holder_front=-1).validate())
    assert any("holder_front" in p for p in Settings(holder_front=151).validate())
