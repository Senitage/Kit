; Kit's desk app installer (Inno Setup 6). Built by build.ps1, which passes AppVersion.
; Installs for the current user only, so no admin rights are needed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C4E3F7A-5D2B-4E61-9A57-3C1F0B6D2E94}
AppName=Kit
AppVersion={#AppVersion}
AppVerName=Kit {#AppVersion}
AppPublisher=Dan
DefaultDirName={autopf}\Kit Desk
DefaultGroupName=Kit
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=build\installer
OutputBaseFilename=Kit-Desk-Setup-{#AppVersion}
SetupIconFile=build\kit.ico
UninstallDisplayIcon={app}\Kit.exe
UninstallDisplayName=Kit
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start Kit when I log on"; GroupDescription: "Starting Kit:"
Name: "desktopicon"; Description: "Put Kit on the desktop"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "build\dist\Kit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Kit's Chrome extension, for Load unpacked in chrome://extensions (tray menu > Set up the Chrome extension).
Source: "..\..\src\kit\desk\browser_extension\*"; DestDir: "{app}\chrome-extension"; Flags: ignoreversion

[Icons]
Name: "{group}\Kit"; Filename: "{app}\Kit.exe"
Name: "{autodesktop}\Kit"; Filename: "{app}\Kit.exe"; Tasks: desktopicon

[Registry]
; The same value the app's own "Start Kit when I log on" setting writes.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Kit Desk"; ValueData: """{app}\Kit.exe"" --background"; Tasks: startup

[Run]
Filename: "{app}\Kit.exe"; Description: "Start Kit now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Kit.exe /F"; Flags: runhidden; RunOnceId: "StopKit"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Remove start-at-logon whether the installer or the app's settings turned it on.
    Kit's settings and token in %APPDATA%\Kit Desk are kept, so a reinstall
    reconnects without asking again. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Kit Desk');
end;
