#!/bin/sh
# Build the macOS app and a .dmg. Must be run ON A MAC, from the project root:
#   python3 -m venv .venv && . .venv/bin/activate
#   pip install -r requirements.txt -r requirements-desktop.txt pillow
#   sh packaging/build_mac.sh
# (pillow lets PyInstaller convert icon.png to the Mac .icns format.)
set -e
cd "$(dirname "$0")/.."
python -m pytest -q
python packaging/make_icon.py
python -m PyInstaller --noconfirm --distpath dist --workpath build packaging/plotter.spec
rm -f "dist/P1S-Plotter.dmg"
hdiutil create -volname "P1S Plotter" -srcfolder "dist/P1S Plotter.app" -ov -format UDZO "dist/P1S-Plotter.dmg"
echo "Built dist/P1S-Plotter.dmg (unsigned: first launch needs right-click > Open)"
