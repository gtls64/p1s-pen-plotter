"""G-code -> Bambu .gcode.3mf (a zip that Bambu Studio opens as an already-sliced plate).

The file list and metadata copy a real Bambu Studio 02.08 export of a sliced P1S plate
(samples/reference.gcode.3mf). The printer profile in app/bambu/project_settings.json comes from
that export with all of its G-code snippets emptied (packaging/make_bambu_template.py).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import struct
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

from .geometry import BED_SIZE_MM, Polyline, bbox

PRINTER_MODEL_ID = "C12"  # Bambu Lab P1S
NOZZLE_DIAMETER = "0.4"
BAMBU_VERSION = "02.08.02.61"  # Bambu Studio version of the reference export
THUMB_PX = 512
SMALL_THUMB_PX = 128
PROJECT_SETTINGS_PATH = Path(__file__).resolve().parent / "bambu" / "project_settings.json"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
 <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>
"""

MODEL_SETTINGS_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/Metadata/plate_1.gcode" Id="rel-1" Type="http://schemas.bambulab.com/package/2021/gcode"/>
</Relationships>
"""

MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1"/>
    <metadata key="filament_volume_maps" value="0"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>
  </plate>
</config>
"""

CUT_INFORMATION = """<?xml version="1.0" encoding="utf-8"?>
<objects>
</objects>
"""

FILAMENT_SEQUENCE = '{"plate_1":{"nozzle_sequence":[0],"optimal_assignment":[0],"sequence":[1]}}'


def _xml_text(s: str) -> str:
    return quoteattr(s)[1:-1]


def _model_xml(title: str, today: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">BambuStudio-{BAMBU_VERSION}</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">{today}</metadata>
 <metadata name="ModificationDate">{today}</metadata>
 <metadata name="Title">{_xml_text(title)}</metadata>
 <resources>
 </resources>
 <build/>
</model>
"""


def _slice_info(prediction_s: int, pause_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="{BAMBU_VERSION}"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="extruder_type" value="0"/>
    <metadata key="nozzle_volume_type" value="0"/>
    <metadata key="printer_model_id" value="{PRINTER_MODEL_ID}"/>
    <metadata key="nozzle_diameters" value="{NOZZLE_DIAMETER}"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="{prediction_s}"/>
    <metadata key="weight" value="0.00"/>
    <metadata key="pause_count" value="{pause_count}"/>
    <metadata key="first_layer_time" value="0"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="false"/>
    <metadata key="label_object_enabled" value="false"/>
    <metadata key="support_material_on_wipe_tower" value="false"/>
    <metadata key="enable_filament_dynamic_map" value="false"/>
    <metadata key="has_filament_switcher" value="false"/>
    <metadata key="filament_maps" value="1"/>
    <metadata key="limit_filament_maps" value="0"/>
    <filament id="1" tray_info_idx="GFL99" type="PLA" color="#161616" used_m="0.00" used_g="0.00" group_id="0" nozzle_diameter="0.40" volume_type="Standard" used_for_object="true" used_for_support="false" total_load_time="0.00" total_unload_time="0.00"/>
    <nozzle id="0" extruder_id="1" nozzle_diameter="{NOZZLE_DIAMETER}" volume_type="Standard"/>
    <layer_filament_lists>
      <layer_filament_list filament_list="0" layer_ranges="0 0" />
    </layer_filament_lists>
  </plate>
</config>
"""


def _plate_json(polys: list[Polyline]) -> str:
    """Bounding box of the drawing (pen coordinates, mm) in Bambu's plate_1.json format."""
    box = list(bbox(polys)) if polys else [0.0, 0.0, 0.0, 0.0]
    return json.dumps({
        "bbox_all": box, "bbox_objects": [], "bed_type": "textured_plate", "filament_colors": ["#161616"],
        "filament_ids": [0], "first_extruder": 0, "first_layer_time": 0, "is_seq_print": False,
        "nozzle_diameter": float(NOZZLE_DIAMETER), "version": 2,
    })


def project_settings() -> bytes:
    """The bundled P1S profile (all G-code snippets empty), as written into Metadata/project_settings.config."""
    return PROJECT_SETTINGS_PATH.read_bytes()


def gcode_md5(gcode: bytes) -> str:
    """Uppercase hex MD5, as Bambu Studio writes it."""
    return hashlib.md5(gcode).hexdigest().upper()


def _png_rgb(img: np.ndarray) -> bytes:
    """Encode an (h, w, 3) uint8 array as PNG using only the standard library."""
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def thumbnail_png(polys: list[Polyline], px: int = THUMB_PX) -> bytes:
    """Plate thumbnail: the drawing in pen coordinates (mm) on a white square bed."""
    img = np.full((px, px, 3), 255, dtype=np.uint8)
    k = px / BED_SIZE_MM
    for poly in polys:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            n = max(2, math.ceil(math.dist((x0, y0), (x1, y1)) * k * 2))
            t = np.linspace(0, 1, n)
            cols = np.clip(((x0 + (x1 - x0) * t) * k).astype(int), 0, px - 1)
            rows = np.clip(((BED_SIZE_MM - (y0 + (y1 - y0) * t)) * k).astype(int), 0, px - 1)
            img[rows, cols] = (20, 20, 20)
    return _png_rgb(img)


def build_gcode_3mf(gcode: str, prediction_s: float, title: str = "drawing", polys: list[Polyline] | None = None) -> bytes:
    """Package G-code as a .gcode.3mf; prediction_s is the estimated print time in seconds."""
    data = gcode.encode("utf-8")
    polys = polys or []
    thumb = thumbnail_png(polys)
    pauses = sum(1 for line in gcode.splitlines() if line.startswith(("M400 U1", "G4 S")))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", _model_xml(title, dt.date.today().isoformat()))
        z.writestr("Metadata/plate_1.png", thumb)
        z.writestr("Metadata/plate_1_small.png", thumbnail_png(polys, SMALL_THUMB_PX))
        z.writestr("Metadata/plate_no_light_1.png", thumb)
        z.writestr("Metadata/top_1.png", thumb)
        z.writestr("Metadata/pick_1.png", thumb)
        z.writestr("Metadata/plate_1.json", _plate_json(polys))
        z.writestr("Metadata/project_settings.config", project_settings())
        z.writestr("Metadata/plate_1.gcode", data)
        z.writestr("Metadata/plate_1.gcode.md5", gcode_md5(data))
        z.writestr("Metadata/_rels/model_settings.config.rels", MODEL_SETTINGS_RELS)
        z.writestr("Metadata/model_settings.config", MODEL_SETTINGS)
        z.writestr("Metadata/cut_information.xml", CUT_INFORMATION)
        z.writestr("Metadata/slice_info.config", _slice_info(int(round(prediction_s)), pauses))
        z.writestr("Metadata/filament_sequence.json", FILAMENT_SEQUENCE)
    return buf.getvalue()
