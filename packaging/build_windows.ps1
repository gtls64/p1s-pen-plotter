# Build the Windows desktop app and, if Inno Setup 6 is installed, the installer.
# Run from the project root with the venv's packages installed:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

& $py packaging\make_icon.py
& $py -m PyInstaller --noconfirm --distpath dist --workpath build packaging\plotter.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "App folder: dist\P1S Plotter\P1S Plotter.exe"

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    # Inno Setup cannot read paths over 260 characters, so package from a short temporary copy.
    $stage = Join-Path $env:LOCALAPPDATA "Temp\p1s-plotter-build"
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    New-Item -ItemType Directory -Force $stage | Out-Null
    Copy-Item "dist\P1S Plotter" (Join-Path $stage "app") -Recurse
    & $iscc /Q "/DAppSource=$stage\app" packaging\installer.iss
    $code = $LASTEXITCODE
    Remove-Item $stage -Recurse -Force
    if ($code -ne 0) { throw "Inno Setup failed." }
    Write-Host "Installer: dist\P1S-Plotter-Setup-<version>.exe (version set in packaging\installer.iss)"
} else {
    Write-Host "Inno Setup 6 not found - skipped the installer. Get it from https://jrsoftware.org/isinfo.php"
}
