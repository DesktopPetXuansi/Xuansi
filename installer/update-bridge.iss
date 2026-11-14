; One-time bridge from the 0.9.0 in-place installation to versioned updates.

[Setup]
AppId={{71320140-4102-455D-A447-D5D4547BC808}
AppName=玄司 AI 桌宠
AppVersion={#AppVersion}
AppPublisher=DesktopPetXuansi
DefaultDirName={localappdata}\Programs\Xuansi
DefaultGroupName=玄司 AI 桌宠
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=Xuansi-{#AppVersion}-windows-x64-bridge
SetupIconFile={#Payload}\assets\xuansi\icon.ico
UninstallDisplayIcon={app}\versions\{#AppVersion}\assets\xuansi\icon.ico
LicenseFile={#Payload}\LICENSE
InfoBeforeFile={#ProjectRoot}\installer\安装须知.txt
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "{#Payload}\Xuansi.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Payload}\*"; DestDir: "{app}\versions\{#AppVersion}"; Excludes: "\Xuansi.exe,\web\*,\updater\*,\tests\*,\docs\prototypes\*,\assets\xuansi\rigging\*.psd,\assets\xuansi\rigging\*.cmo3"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
var
  BridgeReady: Boolean;

function Quote(Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\.venv\Scripts\pythonw.exe')) then
    Result := '此桥接包需要现有 0.9.0 安装版。请先安装旧版，或选择原安装目录。'
  else if FileExists(ExpandConstant('{app}\data\app.lock')) then
    Result := '请先完全退出玄司，再运行桥接安装。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  Started: Boolean;
  Root, Candidate, Arguments: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Root := ExpandConstant('{app}');
  Candidate := ExpandConstant('{app}\versions\{#AppVersion}');
  WizardForm.StatusLabel.Caption := '正在准备独立版本并检查启动…';
  Arguments := '-B -X utf8 ' + Quote(Candidate + '\scripts\prepare_update_bridge.py') +
    ' --root ' + Quote(Root) + ' --version {#AppVersion}';
  Started := Exec(Candidate + '\runtime\python\python.exe', Arguments, Candidate, SW_HIDE,
    ewWaitUntilTerminated, ExitCode);
  BridgeReady := Started and (ExitCode = 0);
  if BridgeReady then begin
    Arguments := '-NoProfile -ExecutionPolicy Bypass -File ' +
      Quote(Candidate + '\scripts\switch_update_shortcuts.ps1') +
      ' -Root ' + Quote(Root) + ' -Version {#AppVersion}';
    Started := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Arguments, Root, SW_HIDE, ewWaitUntilTerminated, ExitCode);
    BridgeReady := Started and (ExitCode = 0);
  end;
  if not BridgeReady then
    SuppressibleMsgBox('桥接未完成。旧程序和用户数据仍在原目录；请检查安装日志并重试。',
      mbError, MB_OK, IDOK);
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if not BridgeReady then Result := 1;
end;
