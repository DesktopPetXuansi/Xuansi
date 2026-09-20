; 按当前用户安装；依赖下载沿用已校验的 setup.ps1，失败不能显示为安装成功。
[Setup]
AppId={{71320140-4102-455D-A447-D5D4547BC808}
AppName=玄司 AI 桌宠
AppVersion={#AppVersion}
AppPublisher=DesktopPetXuansi
AppPublisherURL=https://github.com/DesktopPetXuansi/Xuansi
DefaultDirName={localappdata}\Programs\Xuansi
DefaultGroupName=玄司 AI 桌宠
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=Xuansi-{#AppVersion}-windows-x64-setup
SetupIconFile={#Payload}\assets\xuansi\icon.ico
UninstallDisplayIcon={app}\assets\xuansi\icon.ico
LicenseFile={#Payload}\LICENSE
InfoBeforeFile={#ProjectRoot}\installer\安装须知.txt
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式（安装版）"; Flags: unchecked

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\玄司 AI 桌宠"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m pet"; WorkingDir: "{app}"; IconFilename: "{app}\assets\xuansi\icon.ico"
Name: "{userdesktop}\玄司 AI 桌宠（安装版）"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m pet"; WorkingDir: "{app}"; IconFilename: "{app}\assets\xuansi\icon.ico"; Tasks: desktopicon
Name: "{group}\重新下载依赖与模型"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup.ps1"" -SkipShortcuts"; WorkingDir: "{app}"

[Code]
var
  DependenciesReady: Boolean;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not DirExists('D:\') then
    Result := '本版本需要 D 盘保存模型：D:\AI\Models\desktop-pet。请先准备 D 盘，或按 README 使用源码安装。';
  Log('检查固定模型目录的所在磁盘。');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode, ShowMode: Integer;
  Started: Boolean;
begin
  if CurStep <> ssPostInstall then Exit;
  WizardForm.StatusLabel.Caption := '正在联网安装依赖、下载和校验模型，首次安装可能需要较长时间……';
  Log('开始 setup.ps1；详细记录位于应用目录的 data\setup.log。');
  ShowMode := SW_SHOWNORMAL;
  if WizardSilent then ShowMode := SW_HIDE;
  Started := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup.ps1') + '" -SkipShortcuts',
    ExpandConstant('{app}'), ShowMode, ewWaitUntilTerminated, ExitCode);
  DependenciesReady := Started and (ExitCode = 0);
  Log(Format('依赖安装完成：started=%d, exit=%d', [Ord(Started), ExitCode]));
  if not DependenciesReady then begin
    SuppressibleMsgBox('依赖或模型安装失败。请检查 data\setup.log，联网后重新运行安装包以继续下载。', mbError, MB_OK, IDOK);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not DependenciesReady then begin
    WizardForm.FinishedHeadingLabel.Caption := '依赖或模型尚未安装完成';
    WizardForm.FinishedLabel.Caption := '程序文件已保存，但现在还不能使用。请检查应用目录 data\setup.log，在开始菜单选择“重新下载依赖与模型”或重新运行安装包。';
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if not DependenciesReady then Result := 1;
end;
