"""Machine settings for the pen plotter, persisted as settings.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

MIN_Z_DRAW_MM = 0.5  # below this the nozzle itself would be on the paper
PEN_LENGTH_MM = 6.0  # the pen tip is always set exactly this far below the nozzle tip...
SETTING_CUBE_MM = 10.0  # ...by resting it on a cube this tall while the nozzle waits at PEN_SET_Z_MM
PEN_SET_Z_MM = SETTING_CUBE_MM + PEN_LENGTH_MM  # nozzle Z while fitting/changing the pen
MAX_Z_LIFT_MM = PEN_SET_Z_MM - 1.0  # pen-up stays below the pen-setting height
MIN_PEN_WIDTH_MM = 0.05
MAX_PEN_WIDTH_MM = 5.0
PEN_WIDTH_PRESETS_MM = (0.2, 0.3, 0.5, 0.8, 1.0)
MIN_LIFT_CLEARANCE_MM = 1.0  # pen-up must hold the tip at least this far above the paper
FRONT_CLEARANCE_MM = 5.0  # gap kept between the front of the holder and the front edge of the bed (Y0)
MAX_HOLDER_FRONT_MM = 150.0


@dataclass
class Settings:
    """Plotter settings.

    offset_x/offset_y: pen position minus nozzle position, mm.
    z_draw: nozzle Z (mm) at which the pen presses on the paper.
    z_lift: nozzle Z (mm) for pen-up travel.
    draw_speed, travel_speed, z_speed: mm/min.
    pause_seconds: 0 = wait for Resume (M400 U1); > 0 = timed pause (G4 S<n>), seconds.
    pen_width: width of the line the pen draws, mm (used for the preview and for fill/hatch spacing).
    pen_length (fixed, PEN_LENGTH_MM): how far the pen tip sticks out below the nozzle tip, mm. With the
        nozzle at Z the pen tip is at Z - pen_length, so pen_length - z_draw is how far the spring is pressed.
    holder_front: how far the pen holder reaches in front of the nozzle (towards -Y), mm. The holder is
        always attached, so every move keeps the nozzle at Y >= holder_front + FRONT_CLEARANCE_MM.
    """

    offset_x: float = 0.0
    offset_y: float = 0.0
    z_draw: float = 5.0
    z_lift: float = 9.0
    draw_speed: float = 1500.0
    travel_speed: float = 6000.0
    z_speed: float = 600.0
    pause_seconds: float = 0.0
    pen_width: float = 0.4
    holder_front: float = 60.0  # the user's holder; 0 = no holder reach (pen stop back at Y20)

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty if the settings are usable)."""
        errors: list[str] = []
        if self.z_draw < MIN_Z_DRAW_MM:
            errors.append(f"z_draw must be at least {MIN_Z_DRAW_MM} mm so the nozzle never touches the paper.")
        if self.z_lift <= self.z_draw:
            errors.append("z_lift must be higher than z_draw.")
        if self.z_lift > MAX_Z_LIFT_MM:
            errors.append(f"z_lift must be {MAX_Z_LIFT_MM:g} mm or less (below the pen-setting height of "
                          f"Z{PEN_SET_Z_MM:g}).")
        for name in ("draw_speed", "travel_speed", "z_speed"):
            if getattr(self, name) <= 0:
                errors.append(f"{name} must be greater than 0 mm/min.")
        if self.pause_seconds < 0:
            errors.append("pause_seconds cannot be negative.")
        if not MIN_PEN_WIDTH_MM <= self.pen_width <= MAX_PEN_WIDTH_MM:
            errors.append(f"pen_width must be between {MIN_PEN_WIDTH_MM:g} and {MAX_PEN_WIDTH_MM:g} mm.")
        if self.z_lift < self.pen_length + MIN_LIFT_CLEARANCE_MM:
            errors.append(f"z_lift must be at least pen_length + {MIN_LIFT_CLEARANCE_MM:g} mm "
                          f"({self.pen_length + MIN_LIFT_CLEARANCE_MM:g} mm) so pen-up lifts the tip off the paper.")
        if not 0 <= self.holder_front <= MAX_HOLDER_FRONT_MM:
            errors.append(f"holder_front must be between 0 and {MAX_HOLDER_FRONT_MM:g} mm.")
        for name in ("offset_x", "offset_y"):
            if abs(getattr(self, name)) >= 128:
                errors.append(f"{name} must be smaller than 128 mm.")
        return errors

    def min_nozzle_y(self) -> float:
        """Lowest nozzle Y (mm) that keeps the holder clear of the front; 0 if no holder reach is set."""
        return self.holder_front + FRONT_CLEARANCE_MM if self.holder_front > 0 else 0.0

    @property
    def pen_length(self) -> float:
        """Pen tip distance below the nozzle tip, mm: fixed, set with the cube at every pen pause."""
        return PEN_LENGTH_MM

    def press_depth(self) -> float:
        """How far the pen tip is pushed into the paper at z_draw, mm (negative = it stops above the paper)."""
        return self.pen_length - self.z_draw


def settings_from_dict(data: dict[str, Any]) -> Settings:
    """Build Settings from a dict, ignoring unknown keys and missing values."""
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: float(v) for k, v in data.items() if k in known and v is not None})


def load_settings(path: Path) -> Settings:
    """Load settings from a JSON file, falling back to defaults if it is missing or unreadable."""
    try:
        return settings_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    """Write settings to a JSON file."""
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
