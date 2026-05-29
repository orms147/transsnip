; Inno Setup script — wraps the PyInstaller onedir bundle (dist\TransSnip)
; into a single TransSnip-Setup.exe that non-technical users can run.
;
; Build steps:
;   1. pyinstaller --noconfirm --clean TransSnip.spec      (produces dist\TransSnip)
;   2. Open this file in Inno Setup and click Compile,
;      or:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;   3. Result: dist\installer\TransSnip-Setup.exe

#define MyAppName "TransSnip"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "orms147"
#define MyAppExeName "TransSnip.exe"

[Setup]
AppId={{B7E3F2A1-5C4D-4E8B-9A2F-TRANSSNIP0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install — no UAC prompt, installs to the user's profile.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=TransSnip-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 64-bit only (onnxruntime / PySide6 wheels are x64)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; No elevation: per-user install, and the HKCU "run on startup" entry lands
; in the correct user's profile (this also clears the admin/HKCU warning).
PrivilegesRequired=lowest
; SetupIconFile=assets\app.ico   ; uncomment once an .ico exists

[Languages]
Name: "vietnamese"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tao shortcut ngoai Desktop"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Chay TransSnip cung Windows (khuyen dung cho app tray)"; GroupDescription: "Tuy chon:"

[Files]
; Copy the entire PyInstaller onedir output
Source: "dist\TransSnip\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Go cai dat {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; "Run on startup" — per-user HKCU Run entry, removed on uninstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; \
    Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mo {#MyAppName} ngay"; \
    Flags: nowait postinstall skipifsilent
