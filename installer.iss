; Inno Setup script for JARVIS.
; Compile with: iscc installer.iss
; Expects the PyInstaller onedir build to already exist at dist\JARVIS\
; (see mark48.spec). Output lands in installer_output\JARVIS-Setup.exe.

#ifndef MyAppVersion
  #define MyAppVersion "48.0.0"
#endif

#define MyAppName "JARVIS"
#define MyAppPublisher "TechInATux"
#define MyAppExeName "JARVIS.exe"
#define MySourceDir "dist\JARVIS"

[Setup]
; This GUID was rotated from the original {{B1F2C6A0-6C1E-4C7B-9C7A-6C6D3D6E9A48}}
; used back when this app was branded "MARK XLVIII" (DefaultDirName was
; {localappdata}\Programs\MarkXLVIII). Inno Setup keys its uninstall/upgrade
; registry entry (HKCU\...\Uninstall\{AppId}_is1) purely by AppId and remembers
; the *original* install path forever via "Inno Setup: App Path" — so on any
; machine that ever ran the old MarkXLVIII-branded build, every later install
; using the same AppId (this one, pre-rotation) silently reused that old path
; instead of the new DefaultDirName below, even after uninstalling/deleting the
; folder, because the registry association wasn't guaranteed to be cleared.
; Do not revert this to the old GUID.
AppId={{C42C19AC-6121-427A-B51D-8F43FD863E48}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install under %LocalAppData%\Programs — no admin/UAC prompt needed.
DefaultDirName={localappdata}\Programs\JARVIS
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=JARVIS-Setup
SetupIconFile=config\jarvis.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Uninstall removes the install directory but intentionally leaves
; %AppData%\JARVIS (API key, preferences, memory) untouched so a
; reinstall doesn't force the user through onboarding again.
