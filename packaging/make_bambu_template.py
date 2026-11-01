"""Build app/bambu/project_settings.json from a real Bambu Studio export (samples/reference.gcode.3mf).

Bambu Studio refuses a .gcode.3mf without Metadata/project_settings.config ("invalid config"),
so the app ships this profile. Every G-code snippet in it (start, end, filament change,
timelapse...) is emptied so nothing in the package can heat or extrude, even if re-sliced.

Run again after exporting a newer reference:  python packaging/make_bambu_template.py
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "samples" / "reference.gcode.3mf"
OUT = ROOT / "app" / "bambu" / "project_settings.json"


def sanitise(settings: dict) -> dict:
    """Copy of a Bambu project_settings dict with every *_gcode value emptied and every bed-plate
    temperature set to 0 (the bed warmed up although our G-code never heats it; these may be why)."""
    out = dict(settings)
    for key in out:
        if key.endswith("_gcode"):
            out[key] = [""] * len(out[key]) if isinstance(out[key], list) else ""
        elif "_plate_temp" in key:
            out[key] = ["0"] * len(out[key]) if isinstance(out[key], list) else "0"
    return out


def main(reference: Path = REFERENCE) -> None:
    with zipfile.ZipFile(reference) as z:
        settings = json.loads(z.read("Metadata/project_settings.config"))
    if settings.get("printer_model") != "Bambu Lab P1S":
        sys.exit(f"Reference is for {settings.get('printer_model')!r}, expected 'Bambu Lab P1S'.")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(sanitise(settings), indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} (Bambu Studio {settings.get('version')})")


if __name__ == "__main__":
    main()
