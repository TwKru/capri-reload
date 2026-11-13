; Inno Setup 6: user-level installation, no Python or administrator rights required.
#ifndef AppSource
#define AppSource "..\dist\Capri"
#endif
[Setup]
AppId=CapriReloadDesktop
AppName=Capri Reload
AppVersion=2026.11.13
DefaultDirName={localappdata}\Programs\Capri
DefaultGroupName=Capri
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Capri-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dark
WizardSizePercent=115
SetupIconFile=..\assets\ui\capri-chip.ico
WizardImageFile=..\assets\ui\installer-banner.bmp
WizardSmallImageFile=..\assets\ui\installer-mark.bmp
DisableWelcomePage=no
DisableProgramGroupPage=yes
AppPublisher=Capri
CloseApplications=yes
UninstallDisplayIcon={app}\Capri.exe
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Excludes: "config.json,memory.json,me.md,personality.md,personality.backup.md,jobs.sqlite*,*.log,*.capri-backup,\torch\include,\torch\include\*,\torch\share\cmake,\torch\share\cmake\*,\torch\test,\torch\test\*"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Capri"; Filename: "{app}\Capri.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Capri"; Filename: "{app}\Capri.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"
[Run]
Filename: "{app}\Capri.exe"; Parameters: "--setup --setup-mode={code:GetSetupMode}"; Description: "Настроить и запустить Капри"; Flags: nowait postinstall skipifsilent

[Code]
var
  AIModePage: TInputOptionWizardPage;

procedure InitializeWizard;
begin
  AIModePage := CreateInputOptionPage(wpSelectDir,
    'Как Капри будет отвечать?', 'Выбери удобный способ подключения ИИ',
    'Голос и обычные команды работают на компьютере в обоих режимах. Подключение настроим в графическом мастере после установки.',
    True, False);
  AIModePage.Add('Локальный ИИ — без ключей API. Модель загрузится отдельно (от 2,5 ГБ).');
  AIModePage.Add('Облачный API — подключить свой ключ OpenAI, Gemini или другого сервиса.');
  AIModePage.SelectedValueIndex := 0;
end;

function GetSetupMode(Param: String): String;
begin
  if AIModePage.SelectedValueIndex = 1 then Result := 'api'
  else Result := 'local';
end;
