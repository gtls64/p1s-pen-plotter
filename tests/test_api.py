from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "SETTINGS_PATH", tmp_path / "settings.json")
    return TestClient(main.app)


def upload(client: TestClient, name: str = "shapes.svg") -> dict:
    res = client.post("/api/upload", files={"file": (name, (SAMPLES / name).read_bytes(), "image/svg+xml")})
    assert res.status_code == 200, res.text
    return res.json()


def test_index_served(client: TestClient) -> None:
    assert "P1S Pen Plotter" in client.get("/").text


def test_settings_roundtrip(client: TestClient) -> None:
    s = client.get("/api/settings").json()
    s["offset_x"] = -31.5
    assert client.put("/api/settings", json=s).status_code == 200
    assert client.get("/api/settings").json()["offset_x"] == -31.5
    s["z_lift"] = 0.1
    res = client.put("/api/settings", json=s)
    assert res.status_code == 400 and res.json()["detail"]["problems"]


def test_upload_plan_export(client: TestClient) -> None:
    d = upload(client)
    assert d["aspect"] == pytest.approx(70 / 90)  # the outer 90 x 70 rect sets the extents
    body = {"items": [{"id": d["id"], "width_mm": 90, "x_mm": 123, "y_mm": 123}], "name": d["name"]}  # 90 x 70, centred
    plan = client.post("/api/plan", json=body).json()
    assert plan["problems"] == [] and plan["strokes"] == 8 and plan["seconds"] > 0
    xs = [p[0] for poly in plan["polylines"] for p in poly]
    ys = [p[1] for poly in plan["polylines"] for p in poly]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((78, 168, 88, 158), abs=0.01)
    res = client.post("/api/export", json=body)
    assert res.status_code == 200
    assert 'filename="shapes.gcode.3mf"' in res.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert "Metadata/plate_1.gcode" in z.namelist()
    assert client.post("/api/export?fmt=gcode", json=body).text.startswith("; HEADER_BLOCK_START")


def test_export_refused_off_bed(client: TestClient) -> None:
    d = upload(client)
    body = {"items": [{"id": d["id"], "width_mm": 100, "x_mm": 250, "y_mm": 60}]}
    assert client.post("/api/plan", json=body).json()["problems"]
    res = client.post("/api/export", json=body)
    assert res.status_code == 400
    assert "outside the bed" in res.json()["detail"]["problems"][0]


def test_upload_rejects_non_svg(client: TestClient) -> None:
    res = client.post("/api/upload", files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert res.status_code == 400


def test_calibration_endpoints(client: TestClient) -> None:
    plan = client.get("/api/calibration/plan").json()
    assert plan["strokes"] == 3 and plan["problems"] == []
    assert client.get("/api/calibration/export").status_code == 200


def test_colours_become_pens(client: TestClient) -> None:
    d = upload(client, "colours.svg")
    assert [c["colour"] for c in d["colours"]] == ["#000000", "#ff0000", "#e53935", "#1e5adc"]
    body = {"items": [{"id": d["id"], "width_mm": 120, "x_mm": 128, "y_mm": 128}], "name": d["name"]}
    plan = client.post("/api/plan", json=body).json()  # default: one pen per colour
    assert plan["problems"] == [] and plan["pen_changes"] == 3
    assert sum(layer["strokes"] for layer in plan["layers"]) == plan["strokes"] == len(plan["polylines"])
    # Both reds on pen 1, black on pen 2, blue skipped.
    body["pens"] = [["#ff0000", "#e53935"], ["#000000"]]
    plan = client.post("/api/plan", json=body).json()
    assert [layer["colour"] for layer in plan["layers"]] == ["#ff0000", "#000000"] and plan["pen_changes"] == 1
    gcode = client.post("/api/export?fmt=gcode", json=body).text
    assert gcode.count("; PEN_CHANGE ") == 1
    body["pens"] = []
    assert "Nothing to draw." in client.post("/api/plan", json=body).json()["problems"]
    assert client.post("/api/export", json=body).status_code == 400


def test_several_svgs_scaled_moved_and_rotated(client: TestClient) -> None:
    a, b = upload(client, "shapes.svg"), upload(client, "colours.svg")
    body = {"items": [
        {"id": a["id"], "width_mm": 90, "x_mm": 70, "y_mm": 190},
        {"id": b["id"], "width_mm": 80, "x_mm": 180, "y_mm": 120, "rotation_deg": 90},
    ], "name": "two"}
    plan = client.post("/api/plan", json=body).json()
    assert plan["problems"] == []
    assert plan["strokes"] == 8 + 5
    # Colours from both SVGs share pens: black (both), then the colours.svg colours.
    assert [layer["colour"] for layer in plan["layers"]] == ["#000000", "#ff0000", "#e53935", "#1e5adc"]
    xs = [p[0] for poly in plan["polylines"] for p in poly]
    ys = [p[1] for poly in plan["polylines"] for p in poly]
    # shapes: 90 x 70 around (70, 190); colours: 80 wide, turned 90 degrees, so 80 tall around (180, 120).
    assert min(xs) == pytest.approx(25, abs=0.01) and max(xs) == pytest.approx(180 + 80 * b["aspect"] / 2, abs=0.01)
    assert min(ys) == pytest.approx(80, abs=0.01) and max(ys) == pytest.approx(225, abs=0.01)
    assert client.post("/api/export", json=body).status_code == 200


def test_unknown_svg_id(client: TestClient) -> None:
    body = {"items": [{"id": "nope", "width_mm": 50, "x_mm": 128, "y_mm": 128}]}
    assert client.post("/api/plan", json=body).status_code == 404


def test_stretched_svg(client: TestClient) -> None:
    d = upload(client)  # shapes.svg: 90 x 70 units
    body = {"items": [{"id": d["id"], "width_mm": 90, "height_mm": 35, "x_mm": 128, "y_mm": 128}]}
    plan = client.post("/api/plan", json=body).json()
    ys = [p[1] for poly in plan["polylines"] for p in poly]
    assert (min(ys), max(ys)) == pytest.approx((110.5, 145.5), abs=0.01)
