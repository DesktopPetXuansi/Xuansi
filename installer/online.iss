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
MinVersion=10.0.17763
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=Xuansi-{#AppVersion}-windows-x64-setup
SetupIconFile={#Payload}\assets\xuansi\icon.ico
UninstallDisplayIcon={app}\assets\xuansi\icon.ico
LicenseFile={#Payload}\LICENSE
InfoBeforeFile={#ProjectRoot}\omx_wiki\发布与安装\安装须知.txt
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120,140
SetupLogging=yes
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
DisableDirPage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式（安装版）"; Flags: unchecked

[InstallDelete]
; 同目录升级只删除退役控制模块及其字节码，不触碰用户数据或其他模块。
Type: files; Name: "{app}\pet\model_control.py"
Type: files; Name: "{app}\pet\model_semantics.py"
Type: files; Name: "{app}\pet\speech_control.py"
Type: files; Name: "{app}\pet\__pycache__\model_control.*.pyc"
Type: files; Name: "{app}\pet\__pycache__\model_semantics.*.pyc"
Type: files; Name: "{app}\pet\__pycache__\speech_control.*.pyc"

[Files]
; 前置文件放在 solid 块最前；只提取临时私有 Python、探测代码和锁定纯 Python HTTP 依赖。
Source: "{#Payload}\runtime\python\*"; DestDir: "{tmp}\preflight\runtime\python"; Excludes: "Lib\site-packages\*,Scripts\*"; Flags: dontcopy recursesubdirs createallsubdirs
Source: "{#Payload}\runtime\preflight\*"; DestDir: "{tmp}\preflight"; Flags: dontcopy recursesubdirs createallsubdirs
Source: "{#Payload}\pet\__init__.py"; DestDir: "{tmp}\preflight\pet"; Flags: dontcopy
Source: "{#Payload}\pet\ai\*"; DestDir: "{tmp}\preflight\pet\ai"; Excludes: "__pycache__\*"; Flags: dontcopy recursesubdirs createallsubdirs
Source: "{#Payload}\pet\tool_protocol.py"; DestDir: "{tmp}\preflight\pet"; Flags: dontcopy
Source: "{#Payload}\pet\text_stream.py"; DestDir: "{tmp}\preflight\pet"; Flags: dontcopy
Source: "{#Payload}\pet\model_memory.py"; DestDir: "{tmp}\preflight\pet"; Flags: dontcopy
Source: "{#Payload}\scripts\preflight*.py"; DestDir: "{tmp}\preflight\scripts"; Flags: dontcopy
; 桌面包不携带官网源码；运行时模型保留，PSD、拆分图层和编辑器工程留在源码仓库。
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "\web\*,\assets\xuansi\rigging\blink-mouth-reference.png,\assets\xuansi\rigging\blink-talk-preview.png,\assets\xuansi\rigging\neutral-preview.png,\assets\xuansi\rigging\xuansi-layers.psd,\assets\xuansi\rigging\xuansi.cmo3,\assets\xuansi\rigging\layers.json,\assets\xuansi\rigging\layers\*.png"; Flags: ignoreversion recursesubdirs createallsubdirs
; 安装版资源回归与 Go 共用这份校验样例，显式保留数据文件，不部署官网程序。
Source: "{#Payload}\web\contracts\fixtures\model-references.json"; DestDir: "{app}\web\contracts\fixtures"; Flags: ignoreversion

[Icons]
Name: "{group}\玄司 AI 桌宠"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m pet"; WorkingDir: "{app}"; IconFilename: "{app}\assets\xuansi\icon.ico"
Name: "{userdesktop}\玄司 AI 桌宠（安装版）"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m pet"; WorkingDir: "{app}"; IconFilename: "{app}\assets\xuansi\icon.ico"; Tasks: desktopicon
Name: "{group}\重新下载依赖与模型"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup.ps1"" -SkipShortcuts -InstallPlanPath ""{app}\data\install-plan.json"""; WorkingDir: "{app}"

[Code]
var
  DependenciesReady, ApiVerified, ProbeReady, TempReady: Boolean;
  ModelPage, VoicePage: TInputOptionWizardPage;
  ModelDirPage: TInputDirWizardPage;
  ApiPage: TInputQueryWizardPage;
  ProviderCombo: TNewComboBox;
  ContextEdit, ModeEdit: TNewEdit;
  ContextLabel, ModeLabel: TNewStaticText;
  ProbeLabel: TNewStaticText;
  ProbeButton, VerifyButton: TNewButton;
  BackupBox, OnlineBox: TNewCheckBox;
  PlanSummary: String;

function SetEnvironmentVariable(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function TempPath(Name: String): String;
begin
  Result := ExpandConstant('{tmp}\preflight\') + Name;
end;

function Quote(Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function RunCheck(ScriptName, Arguments: String; TimeoutSeconds: Integer): Boolean;
var
  ExitCode: Integer;
begin
  // 参数不包含 Key；执行时间由标准库 runner 限制，界面不会无限等待。
  Result := Exec(TempPath('runtime\python\python.exe'),
    '-X utf8 ' + Quote(TempPath('scripts\preflight_runner.py')) +
    ' --timeout ' + IntToStr(TimeoutSeconds) + ' ' + Quote(TempPath('scripts\' + ScriptName)) +
    ' ' + Arguments, TempPath(''), SW_HIDE, ewWaitUntilTerminated, ExitCode);
  Result := Result and (ExitCode = 0);
  Log(Format('安装前辅助检查完成：成功=%d，退出=%d', [Ord(Result), ExitCode]));
end;

procedure CleanupApi;
begin
  if TempReady and FileExists(TempPath('verified-profile.json')) then
    RunCheck('preflight_api.py', '--cleanup ' + Quote(TempPath('verified-profile.json')), 15);
  ApiVerified := False;
end;

procedure ApiChanged(Sender: TObject);
begin
  ApiVerified := False;
  VerifyButton.Caption := '验证能力（可能产生少量调用费用）';
end;

procedure ProviderChanged(Sender: TObject);
var
  Section, Presets: String;
begin
  Section := IntToStr(ProviderCombo.ItemIndex);
  Presets := TempPath('presets.ini');
  ApiPage.Values[0] := GetIniString(Section, 'provider', 'custom', Presets);
  ApiPage.Values[1] := GetIniString(Section, 'region', 'custom', Presets);
  ApiPage.Values[2] := GetIniString(Section, 'endpoint', '', Presets);
  ApiPage.Values[3] := GetIniString(Section, 'model', '', Presets);
  ModeEdit.Text := GetIniString(Section, 'mode', 'default', Presets);
  ContextEdit.Text := GetIniString(Section, 'context_tokens', '65536', Presets);
  ApiChanged(Sender);
end;

procedure VerifyApi(Sender: TObject);
var
  Choices: String;
  I: Integer;
  Names: array[0..3] of String;
begin
  CleanupApi;
  Choices := TempPath('profile.ini');
  Names[0] := 'provider'; Names[1] := 'region'; Names[2] := 'endpoint'; Names[3] := 'model';
  for I := 0 to 3 do SetIniString('profile', Names[I], ApiPage.Values[I], Choices);
  SetIniString('profile', 'mode', ModeEdit.Text, Choices);
  SetIniString('profile', 'context_tokens', ContextEdit.Text, Choices);
  if not RunCheck('preflight.py', 'profile --choices ' + Quote(Choices) +
    ' --output ' + Quote(TempPath('profile-draft.json')), 15) then begin
    SuppressibleMsgBox('API 地址或配置无效。请使用 HTTPS（开发回环地址除外），并填写具体模型。', mbError, MB_OK, IDOK);
    Exit;
  end;
  VerifyButton.Enabled := False;
  VerifyButton.Caption := '验证中：最长 200 秒，仅使用合成数据……';
  try
    // Key 仅存在于短时子进程环境，不写命令行、普通 JSON、安装日志或回执。
    if not SetEnvironmentVariable('XUANSI_API_KEY_DRAFT', ApiPage.Values[4]) then Exit;
    try
      ApiVerified := RunCheck('preflight_api.py', '--plan ' + Quote(TempPath('profile-draft.json')) +
        ' --output ' + Quote(TempPath('verified-profile.json')), 200);
    finally
      SetEnvironmentVariable('XUANSI_API_KEY_DRAFT', '');
    end;
    if ApiVerified then begin
      ApiPage.Values[4] := '';
      ApiVerified := True;
      VerifyButton.Caption := '文字、图片、工具、流式、取消验证已通过';
    end else begin
      VerifyButton.Caption := '验证失败，修改配置或 Key 后重新验证';
      SuppressibleMsgBox('能力验证失败或超时，当前选择已保留。请检查鉴权、模型能力、额度和网络；未完成安装。', mbError, MB_OK, IDOK);
    end;
  finally
    SetEnvironmentVariable('XUANSI_API_KEY_DRAFT', '');
    VerifyButton.Enabled := True;
  end;
end;

procedure Probe(Sender: TObject);
var
  Report: String;
  StandardAllowed, LightAllowed: Boolean;
begin
  ProbeButton.Enabled := False;
  ProbeLabel.Caption := '检测中（最长 20 秒），只读取系统和资源，不下载权重……';
  try
    ProbeReady := RunCheck('preflight.py', 'probe --app-dir ' + Quote(WizardDirValue) +
      ' --model-dir ' + Quote(ModelDirPage.Values[0]) + ' --output ' + Quote(TempPath('report')), 20);
    Report := TempPath('report\device.ini');
    StandardAllowed := GetIniString('qwen3.5-9b', 'selectable', '1', Report) = '1';
    LightAllowed := GetIniString('qwen3.5-4b', 'selectable', '1', Report) = '1';
    ModelPage.CheckListBox.ItemEnabled[0] := StandardAllowed;
    ModelPage.CheckListBox.ItemEnabled[1] := LightAllowed;
    ModelPage.CheckListBox.ItemEnabled[2] := GetIniString('base', 'selectable', '1', Report) = '1';
    // 基础/API 与本地模型分别展示；缺失事实保留未知及重试入口。
    ProbeLabel.Caption := '基础/API：' + GetIniString('base', 'reason', '探测未知，可重试', Report) + #13#10 +
      '标准：' + GetIniString('qwen3.5-9b', 'reason', '探测未知，可重试', Report) + #13#10 +
      '轻量：' + GetIniString('qwen3.5-4b', 'reason', '探测未知，可重试', Report);
    Log('基础/API 预检状态：' + GetIniString('base', 'status', 'unknown', Report));
    if not ProbeReady then ProbeLabel.Caption := '探测失败或超时，状态未知。请重新检测，不会当作硬件不兼容。';
    // 已选路线被禁用时保留可见首选，要求用户明确改选，不静默转在线。
  finally
    ProbeButton.Enabled := True;
  end;
end;

procedure InitializeWizard;
var
  I: Integer;
begin
  ExtractTemporaryFiles('{tmp}\preflight\*');
  TempReady := True;
  RunCheck('preflight.py', 'presets --output ' + Quote(TempPath('presets.ini')), 15);
  ModelPage := CreateInputOptionPage(wpSelectDir, '选择推理方式',
    '安装前检查与选择', '检测只作适配估算，不代表实际响应速度。慢速和待验证路线仍可选择。', True, False);
  ModelPage.Add('标准本地：Qwen3.5-9B Q4_K_M');
  ModelPage.Add('轻量本地：Qwen3.5-4B Q4_K_M（实验：语义验收未通过）');
  ModelPage.Add('在线 API：自备 Key，由服务商直接计费');
  ModelPage.SelectedValueIndex := 0;
  ProbeLabel := TNewStaticText.Create(ModelPage);
  ProbeLabel.Parent := ModelPage.Surface;
  ProbeLabel.SetBounds(0, ScaleY(125), ModelPage.SurfaceWidth, ScaleY(95));
  ProbeLabel.WordWrap := True;
  ProbeButton := TNewButton.Create(ModelPage);
  ProbeButton.Parent := ModelPage.Surface;
  ProbeButton.SetBounds(0, ScaleY(225), ScaleX(115), ScaleY(25));
  ProbeButton.Caption := '重新检测';
  ProbeButton.OnClick := @Probe;
  ModelDirPage := CreateInputDirPage(ModelPage.ID, '模型和语音目录',
    '可选择任意有足够空间的目录，无需 D 盘', '应用、模型和临时空间分别核算；旧模型目录保留。', False, '');
  ModelDirPage.Add('模型/语音资源目录：');
  if DirExists('D:\AI\Models\desktop-pet') then ModelDirPage.Values[0] := 'D:\AI\Models\desktop-pet'
  else ModelDirPage.Values[0] := ExpandConstant('{localappdata}\Xuansi\models');
  BackupBox := TNewCheckBox.Create(ModelDirPage);
  BackupBox.Parent := ModelDirPage.Surface;
  BackupBox.SetBounds(0, ScaleY(105), ModelDirPage.SurfaceWidth, ScaleY(25));
  BackupBox.Caption := '额外准备轻量备用（增加下载，验证通过后才可自动切换）';
  OnlineBox := TNewCheckBox.Create(ModelDirPage);
  OnlineBox.Parent := ModelDirPage.Surface;
  OnlineBox.SetBounds(0, ScaleY(140), ModelDirPage.SurfaceWidth, ScaleY(25));
  OnlineBox.Caption := '本地优先，并允许已验证的在线 API 备用';
  VoicePage := CreateInputOptionPage(ModelDirPage.ID, '选择本机语音组件',
    '语音与大模型独立', '未选组件不下载。录音仍在本机识别，安装后不会自动打开麦克风。', False, False);
  VoicePage.Add('整句语音识别（SenseVoice）');
  VoicePage.Add('回复朗读（Melo / Kokoro）');
  VoicePage.Add('实时语音识别（Paraformer）');
  ApiPage := CreateInputQueryPage(VoicePage.ID, '在线 API 配置与验证',
    '用户自备 Key，调用由服务商直接计费', '验证会发送少量合成文字、图片和无副作用工具，可能计费。不会上传屏幕、音频或记忆。');
  ApiPage.Add('服务商：', False);
  ApiPage.Add('地区：', False);
  ApiPage.Add('HTTPS 接口：', False);
  ApiPage.Add('具体模型：', False);
  ApiPage.Add('API Key（仅本次验证使用，随后保存到 Windows 凭据库）：', True);
  ProviderCombo := TNewComboBox.Create(ApiPage);
  ProviderCombo.Parent := ApiPage.Surface;
  ProviderCombo.SetBounds(ApiPage.Edits[0].Left, ApiPage.Edits[0].Top,
    ApiPage.Edits[0].Width, ApiPage.Edits[0].Height);
  ProviderCombo.Style := csDropDownList;
  ProviderCombo.Items.Text := 'OpenAI'#13#10'百炼（北京）'#13#10'百炼（新加坡）'#13#10'DeepSeek'#13#10'Kimi'#13#10'智谱'#13#10'豆包'#13#10'Claude'#13#10'Gemini'#13#10'自定义兼容接口';
  ApiPage.Edits[0].Visible := False;
  for I := 1 to 4 do ApiPage.Edits[I].OnChange := @ApiChanged;
  ModeLabel := TNewStaticText.Create(ApiPage);
  ModeLabel.Parent := ApiPage.Surface;
  ModeLabel.SetBounds(0, ScaleY(260), ScaleX(180), ScaleY(18));
  ModeLabel.Caption := '工作模式：';
  ModeEdit := TNewEdit.Create(ApiPage);
  ModeEdit.Parent := ApiPage.Surface;
  ModeEdit.SetBounds(0, ScaleY(280), ScaleX(220), ScaleY(22));
  ModeEdit.OnChange := @ApiChanged;
  ContextLabel := TNewStaticText.Create(ApiPage);
  ContextLabel.Parent := ApiPage.Surface;
  ContextLabel.SetBounds(ScaleX(240), ScaleY(260), ScaleX(240), ScaleY(18));
  ContextLabel.Caption := '应用上下文预算（token，可修改）：';
  ContextEdit := TNewEdit.Create(ApiPage);
  ContextEdit.Parent := ApiPage.Surface;
  ContextEdit.SetBounds(ScaleX(240), ScaleY(280), ScaleX(220), ScaleY(22));
  ContextEdit.OnChange := @ApiChanged;
  VerifyButton := TNewButton.Create(ApiPage);
  VerifyButton.Parent := ApiPage.Surface;
  VerifyButton.SetBounds(0, ScaleY(325), ApiPage.SurfaceWidth, ScaleY(25));
  VerifyButton.Caption := '验证能力（可能产生少量调用费用）';
  VerifyButton.OnClick := @VerifyApi;
  ProviderCombo.OnChange := @ProviderChanged;
  ProviderCombo.ItemIndex := 0;
  ProviderChanged(ProviderCombo);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ApiPage.ID) and (ModelPage.SelectedValueIndex <> 2) and not OnlineBox.Checked;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Choices, Mode, ModelID, ProfileArgument: String;
  I: Integer;
  VoiceNames: array[0..2] of String;
  Summary: AnsiString;
begin
  Result := True;
  if CurPageID = ModelPage.ID then begin
    if not ProbeReady then Probe(nil);
    Result := ProbeReady and ModelPage.CheckListBox.ItemEnabled[ModelPage.SelectedValueIndex];
  end;
  if CurPageID = ModelDirPage.ID then begin
    Probe(nil);
    Result := ProbeReady;
  end;
  if (CurPageID = ApiPage.ID) and not ApiVerified then begin
    SuppressibleMsgBox('请先点击能力验证并通过。未验证的 API 不能作为完整桌宠或自动回退候选。', mbError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  if (CurPageID = VoicePage.ID) or (CurPageID = ApiPage.ID) then begin
    Choices := TempPath('choices.ini');
    Mode := 'local';
    if ModelPage.SelectedValueIndex = 2 then Mode := 'api';
    ModelID := 'qwen3.5-9b';
    if ModelPage.SelectedValueIndex = 1 then ModelID := 'qwen3.5-4b';
    SetIniString('choices', 'mode', Mode, Choices);
    SetIniString('choices', 'model', ModelID, Choices);
    SetIniString('choices', 'app_dir', WizardDirValue, Choices);
    SetIniString('choices', 'model_dir', ModelDirPage.Values[0], Choices);
    SetIniString('choices', 'backend', 'auto', Choices);
    SetIniString('choices', 'backup', IntToStr(Ord(BackupBox.Checked and (Mode = 'local'))), Choices);
    SetIniString('choices', 'online', IntToStr(Ord(OnlineBox.Checked)), Choices);
    VoiceNames[0] := 'asr'; VoiceNames[1] := 'tts'; VoiceNames[2] := 'realtime';
    for I := 0 to 2 do SetIniString('choices', VoiceNames[I], IntToStr(Ord(VoicePage.Values[I])), Choices);
    ProfileArgument := '';
    if ApiVerified then ProfileArgument := ' --profile ' + Quote(TempPath('verified-profile.json'));
    Result := Result and RunCheck('preflight.py', 'plan --choices ' + Quote(Choices) +
      ' --output ' + Quote(TempPath('install-plan.json')) + ProfileArgument, 20);
    if Result and LoadStringFromFile(TempPath('install-plan.txt'), Summary) then PlanSummary := UTF8Decode(Summary);
    if not Result then SuppressibleMsgBox('无法确认安装计划。请检查资源空间、模型目录和环境报告，返回重新检测。', mbError, MB_OK, IDOK);
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + PlanSummary + NewLine + NewLine +
    '策略：保留用户首选；只使用已选择且已验证的候选。在线记忆检索与后台截图默认关闭。';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(TempPath('install-plan.json')) then Result := '安装计划尚未确认，请返回选择。';
  if ((ModelPage.SelectedValueIndex = 2) or OnlineBox.Checked) and not ApiVerified then
    Result := '在线 API 配置尚未通过完整能力验证，请返回验证。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode, ShowMode: Integer;
  Started: Boolean;
  Arguments: String;
begin
  if CurStep <> ssPostInstall then Exit;
  WizardForm.StatusLabel.Caption := '正在安装运行依赖并校验已选择资源……';
  Log('按已确认安装计划执行 setup.ps1，日志不包含 API Key。');
  ShowMode := SW_SHOWNORMAL;
  if WizardSilent then ShowMode := SW_HIDE;
  Arguments := '-NoProfile -ExecutionPolicy Bypass -File ' + Quote(ExpandConstant('{app}\setup.ps1')) +
    ' -SkipShortcuts -InstallPlanPath ' + Quote(TempPath('install-plan.json'));
  if ApiVerified then Arguments := Arguments + ' -ProfilePath ' + Quote(TempPath('verified-profile.json'));
  Started := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Arguments,
    ExpandConstant('{app}'), ShowMode, ewWaitUntilTerminated, ExitCode);
  DependenciesReady := Started and (ExitCode = 0);
  Log(Format('依赖安装完成：started=%d, exit=%d', [Ord(Started), ExitCode]));
  if DependenciesReady then begin
    // 成功安装保留已经引用的凭据；回执不进入应用目录和安装记录。
    DeleteFile(TempPath('verified-profile.json.credential-receipt'));
  end else begin
    CleanupApi;
    SuppressibleMsgBox('依赖或所选资源安装失败。请检查 data\setup.log，联网后重新运行安装包继续。', mbError, MB_OK, IDOK);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = ModelPage.ID) and not ProbeReady then Probe(nil);
  if (CurPageID = wpFinished) and not DependenciesReady then begin
    WizardForm.FinishedHeadingLabel.Caption := '安装尚未完成';
    WizardForm.FinishedLabel.Caption := '程序文件已保存，但依赖、所选资源或配置尚未完成。请检查 data\setup.log 后重新运行安装包。';
  end;
end;

procedure DeinitializeSetup;
begin
  SetEnvironmentVariable('XUANSI_API_KEY_DRAFT', '');
  if not DependenciesReady then CleanupApi;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if not DependenciesReady then Result := 1;
end;
