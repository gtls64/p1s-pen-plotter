; Inno Setup script: turns dist\P1S Plotter\ into a normal Windows installer.
; Built by packaging\build_windows.ps1, or: ISCC.exe packaging\installer.iss
; Installs for the current user only, so no administrator prompt.

#define AppName "P1S Plotter"
#define AppVersion "0.1.0"
; build_windows.ps1 passes /DAppSource=<short copy of dist\P1S Plotter> because Inno Setup
; cannot read files whose full path is longer than 260 characters.
#ifndef AppSource
  #define AppSource "..\dist\" + AppName
#endif

[Setup]
AppId={{6E1C2B57-9C1A-4B4E-9F0A-5D3C1B2A7E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=P1S Plotter
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=P1S-Plotter-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
