; Inno Setup script for MARK XLVIII.
; Compile with: iscc installer.iss
; Expects the PyInstaller onedir build to already exist at dist\MarkXLVIII\
; (see mark48.spec). Output lands in installer_output\MARK-XLVIII-Setup.exe.

#ifndef MyAppVersion
  #define MyAppVersion "48.0.0"
#endif

#define MyAppName "MARK XLVIII"
#define MyAppPublisher "FatihMakes"
#define MyAppExeName "MarkXLVIII.exe"
#define MySourceDir "dist\MarkXLVIII"

[Setup]
AppId={{B1F2C6A0-6C1E-4C7B-9C7A-6C6D3D6E9A48}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install under %LocalAppData%\Programs — no admin/UAC prompt needed.
DefaultDirName={localappdata}\Programs\MarkXLVIII
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=MARK-XLVIII-Setup
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
; %AppData%\MarkXLVIII (API key, preferences, memory) untouched so a
; reinstall doesn't force the user through onboarding again.
