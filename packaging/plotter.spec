# PyInstaller recipe for the desktop app. Build from the project root:
#   pyinstaller --noconfirm packaging/plotter.spec
# Output: dist/P1S Plotter/ (Windows) or dist/P1S Plotter.app (macOS)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
APP_NAME = "P1S Plotter"
ICON = str(Path(SPECPATH) / ("icon.ico" if sys.platform.startswith("win") else "icon.png"))

a = Analysis(
    [str(ROOT / "plotter_desktop.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "static"), "static"), (str(ROOT / "app" / "bambu"), "app/bambu")],
    # uvicorn picks its event loop and protocol modules by name at runtime, so list them explicitly.
    hiddenimports=collect_submodules("uvicorn"),
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{APP_NAME}.app", icon=ICON, bundle_identifier="local.p1s-plotter")
