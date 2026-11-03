; Inno Setup 6: user-level installation, no Python or administrator rights required.
[Setup]
AppId=CapriReloadDesktop
AppName=Capri Reload
AppVersion=2026.11.03
DefaultDirName={localappdata}\Programs\Capri
DefaultGroupName=Capri
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Capri-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\Capri.exe
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "..\dist\Capri\*"; DestDir: "{app}"; Excludes: "config.json,memory.json,me.md,personality.md,personality.backup.md,jobs.sqlite*,*.log,*.capri-backup"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Capri"; Filename: "{app}\Capri.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Capri"; Filename: "{app}\Capri.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"
[Run]
Filename: "{app}\Capri.exe"; Description: "Запустить Капри"; Flags: nowait postinstall skipifsilent
