from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.gcode import Layer, calibration_job, calibration_polylines, plot_layers_job
from app.package3mf import build_gcode_3mf
from app.settings import Settings

REFERENCE = Path(__file__).resolve().parent.parent / "samples" / "reference.gcode.3mf"
EXPECTED = {
    "[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model", "Metadata/plate_1.gcode",
    "Metadata/plate_1.gcode.md5", "Metadata/model_settings.config", "Metadata/slice_info.config",
    "Metadata/plate_1.png", "Metadata/plate_1_small.png", "Metadata/plate_no_light_1.png", "Metadata/top_1.png",
    "Metadata/pick_1.png", "Metadata/plate_1.json", "Metadata/project_settings.config",
    "Metadata/_rels/model_settings.config.rels", "Metadata/cut_information.xml", "Metadata/filament_sequence.json",
}


def calibration_package() -> tuple[str, float, bytes]:
    job = calibration_job(Settings())
    return job.gcode, job.estimated_seconds, build_gcode_3mf(job.gcode, job.estimated_seconds, "cal", calibration_polylines())


def test_package_contents() -> None:
    gcode_text, seconds, data = calibration_package()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert set(z.namelist()) == EXPECTED
        gcode = z.read("Metadata/plate_1.gcode")
        assert gcode.decode() == gcode_text
        md5 = z.read("Metadata/plate_1.gcode.md5").decode()
        assert md5 == hashlib.md5(gcode).hexdigest().upper()
        info = z.read("Metadata/slice_info.config").decode()
        assert 'key="printer_model_id" value="C12"' in info
        assert f'key="prediction" value="{round(seconds)}"' in info
        assert 'key="pause_count" value="2"' in info  # pen fitting + calibration measuring pause
        assert z.read("Metadata/plate_1.png").startswith(b"\x89PNG")
        assert json.loads(z.read("Metadata/plate_1.json"))["bbox_all"] == pytest.approx([113, 113, 143, 143])


def test_project_settings_has_no_gcode() -> None:
    """The bundled printer profile must not carry any start/end/filament G-code that could heat or extrude."""
    _, _, data = calibration_package()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        settings = json.loads(z.read("Metadata/project_settings.config"))
    assert settings["printer_model"] == "Bambu Lab P1S"
    gcode_keys = [k for k in settings if k.endswith("_gcode")]
    assert "machine_start_gcode" in gcode_keys and "change_filament_gcode" in gcode_keys
    for k in gcode_keys:
        assert settings[k] in ("", []) or all(v == "" for v in settings[k]), k


def test_multi_pen_pause_count() -> None:
    layers = [Layer("#000000", [[(100.0, 100.0), (120.0, 100.0)]]), Layer("#ff0000", [[(100.0, 110.0), (120.0, 110.0)]])]
    job = plot_layers_job(layers, Settings())
    with zipfile.ZipFile(io.BytesIO(build_gcode_3mf(job.gcode, job.estimated_seconds))) as z:
        assert 'key="pause_count" value="2"' in z.read("Metadata/slice_info.config").decode()


@pytest.mark.skipif(not REFERENCE.exists(), reason="no Bambu Studio reference export in samples/")
def test_same_files_as_bambu_studio_export() -> None:
    with zipfile.ZipFile(REFERENCE) as z:
        assert set(z.namelist()) == EXPECTED


def test_project_settings_bed_temperatures_are_zero() -> None:
    """The bed warmed up although our G-code never heats it; the profile's plate temperatures may be why, so they are all 0."""
    _, _, data = calibration_package()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        settings = json.loads(z.read("Metadata/project_settings.config"))
    plate_keys = [k for k in settings if "_plate_temp" in k]
    assert "textured_plate_temp" in plate_keys and "hot_plate_temp_initial_layer" in plate_keys
    for k in plate_keys:
        assert all(v == "0" for v in settings[k]), k
