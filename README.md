# P1S Pen Plotter

Turn a Bambu Lab P1S 3D printer into a pen plotter. Load SVGs, arrange them on the bed, and export a
`.gcode.3mf` file that you open in Bambu Studio and print like any other job. A pen sits in a holder
clipped beside the nozzle.

> ⚠️ **Work in progress:** tested on one P1S so far; expect changes.
>
> **Unofficial project.** Not affiliated with or endorsed by Bambu Lab. You use the generated G-code
> at your own risk; always do a dry run first (see below).

## Features

- Several SVGs on one bed. Move, scale and rotate them on the canvas with Illustrator-style handles,
  or type exact sizes and positions.
- Multi-colour: strokes are grouped by SVG colour, with a pause to swap pens between colours.
- Pen fitting with a 10 mm calibration cube: the job homes first, then parks the head at the front
  at the pen-setting height and waits while you set the pen tip on the cube.
- Calibration job to measure the pen's X/Y offset from the nozzle.
- Windows desktop app (installer) or a local web app in any browser.

## Safety

Every generated job follows these rules, and the test suite checks them:

- Nothing is ever heated (all heaters are set to 0) and nothing is extruded.
- The printer homes **before** the pen is fitted, then pauses so you can fit it.
- The pen and the nozzle always stay inside the 256 × 256 mm bed.
- The head keeps clear of the front wall, allowing for how far the pen holder reaches forward
  (setting *Holder reach*).
- Z never goes below the drawing height.

**Dry run first:** raise *Z draw* by 5 mm in Settings, so the pen draws in the air, and watch one
full job before drawing on paper.

## Getting started

### Install on Windows (no technical setup)

1. **[Download P1S Plotter for Windows](https://github.com/gtls64/p1s-pen-plotter/releases/latest/download/P1S-Plotter-Setup.exe)**
2. Open the downloaded `P1S-Plotter-Setup.exe`.
3. If Windows shows *"Windows protected your PC"*, click **More info**, then **Run anyway**.
   (The app is free and not code-signed, so Windows doesn't recognise it yet.)
4. Click through the installer. No administrator rights needed. Then open **P1S Plotter** from the
   Start menu.

You also need [Bambu Studio](https://bambulab.com/en/download/studio) to send the files to your printer.

### Build the installer yourself

```
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

This needs Python 3.10+ and, for the installer, [Inno Setup 6](https://jrsoftware.org/isinfo.php).

### Run from source

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Open http://localhost:8000. For the desktop window instead, also install `requirements-desktop.txt`
and run `python plotter_desktop.py`.

### Printing

1. In the app, set up your pen in **Settings** (offsets, holder reach, Z heights) and run the
   **Calibrate** job once.
2. Arrange your SVGs on the **Draw** tab and export the `.gcode.3mf`.
3. Open it in Bambu Studio and print. Untick Bed Leveling, Flow Dynamics Calibration and Timelapse.
4. When the printer pauses at the front, put the 10 mm cube under the pen, let the pen tip rest on
   it, tighten the holder, remove the cube and resume. It pauses the same way for each pen change.

## Development

```
pytest
```

- `app/`: FastAPI backend (SVG parsing, geometry, G-code, `.gcode.3mf` packaging)
- `static/index.html`: the whole user interface
- `packaging/`: desktop app and installer build scripts
- `tests/`: unit and safety tests

Contributions are welcome. Any change to the G-code must keep the safety tests passing.

## License

[MIT](LICENSE)
