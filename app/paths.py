"""Where the app finds its bundled files and keeps user data, both in development and in the packaged desktop app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "P1S Plotter"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Folder holding read-only bundled files such as static/."""
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def user_data_dir(platform: str = sys.platform, env: dict[str, str] | None = None) -> Path:
    """Per-user writable folder for the installed app (e.g. %APPDATA%\\P1S Plotter on Windows)."""
    env = dict(os.environ) if env is None else env
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    if platform.startswith("win"):
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / APP_NAME


def data_dir() -> Path:
    """Writable folder for settings.json: P1S_PLOTTER_DATA if set, the user folder when packaged, else the project."""
    override = os.environ.get("P1S_PLOTTER_DATA")
    if override:
        path = Path(override)
    elif is_frozen():
        path = user_data_dir()
    else:
        return PROJECT_ROOT
    path.mkdir(parents=True, exist_ok=True)
    return path
