; ── DeLector Windows 安装器（Inno Setup 6）────────────────────────────────────
; 用途：给「免装 Python、解压双击即用」的便携版补一个**可卸载、可升级**的安装形态。
;
; 设计约束（每条都有理由，勿随手改）：
;  1. **版本号不由本文件维护**：CI 以 /DAppVersion=<APP_VERSION> 传入，单一真相源仍是
;     delector/core/version.py（与 package_windows.py / build.gradle fallback 同口径）。
;     漏传即 #error，不允许本文件自己写死一个版本。
;  2. **per-user 安装**（PrivilegesRequired=lowest → %LOCALAPPDATA%\Programs\DeLector）：
;     便携版的定位是「免管理员、解压即用」；装到 Program Files 会弹 UAC，与定位相悖。
;     PrivilegesRequiredOverridesAllowed=dialog 让需要机器级安装的用户仍可自行提权。
;  3. **绝不删用户数据**：学习数据在 %LOCALAPPDATA%\DeLector（由 desktop.py 管理），
;     与安装目录完全分离。Inno 默认只删安装目录内的东西，这里再显式声明一次，
;     免得将来有人加 [UninstallDelete] 时误伤用户的学习记录。
;  4. **内嵌 WebView2 Evergreen Bootstrapper**（约 1.8MB）：Win10 缺运行时时装完即可用；
;     已装则跳过（注册表 pv 判定）。装失败**不阻断安装**——应用自身还有一道检测与下载入口。
;  5. **未做代码签名**：Windows SmartScreen 会提示「未知发布者」，README 与发布正文已如实写明。
;
; CI 调用示例：
;   iscc /DAppVersion=5.23.5 ^
;        /DPortableDir=D:\a\DeLector-v5.23.5-Windows-x64-Portable ^
;        /DWebView2Setup=D:\a\MicrosoftEdgeWebview2Setup.exe ^
;        installer\DeLector.iss

#ifndef AppVersion
  #error AppVersion 未传入：CI 必须以 /DAppVersion=<APP_VERSION> 调用 ISCC（版本单一真相源 = delector/core/version.py）
#endif
#ifndef PortableDir
  #error PortableDir 未传入：CI 必须以 /DPortableDir=<便携版产物目录> 调用 ISCC
#endif
#ifndef WebView2Setup
  #error WebView2Setup 未传入：CI 必须以 /DWebView2Setup=<MicrosoftEdgeWebview2Setup.exe> 调用 ISCC（内嵌 WebView2 bootstrapper 是本安装器的既定形态）
#endif

[Setup]
AppId={{6F4A2C1E-9B3D-4E7A-8C55-1D2E3F4A5B6C}
AppName=DeLector
AppVersion={#AppVersion}
AppVerName=DeLector {#AppVersion}
DefaultDirName={localappdata}\Programs\DeLector
DefaultGroupName=DeLector
DisableProgramGroupPage=yes
; per-user：免 UAC（见文件头约束 2）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=DeLector-v{#AppVersion}-Windows-x64-Setup
; 产物 246MB 目录 → LZMA2 实体压缩后约 95~120MB
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\DeLector.ico
UninstallDisplayIcon={app}\DeLector.exe
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimplified.SetupReadyNote=本安装器未做代码签名，Windows 可能提示「未知发布者」，选择「更多信息 → 仍要运行」即可。%n%n学习数据保存在 %%LOCALAPPDATA%%\DeLector，卸载本程序不会删除它。
english.SetupReadyNote=This installer is not code-signed, so Windows may show "Unknown publisher" — choose "More info → Run anyway".%n%nYour study data lives in %%LOCALAPPDATA%%\DeLector and is NOT deleted when you uninstall.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 便携版目录整体入包（.build-info.json 与「说明_README.txt」一并带上，指纹与文案不丢）
Source: "{#PortableDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 bootstrapper：不加 deleteafterinstall —— 删文件要等安装结束，而 ssPostInstall 里
; 还要用它（见 [Code]）。用完在代码里显式删。
Source: "{#WebView2Setup}"; DestDir: "{tmp}"; Flags: ignoreversion

[Icons]
Name: "{group}\DeLector"; Filename: "{app}\DeLector.exe"
Name: "{group}\{cm:UninstallProgram,DeLector}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\DeLector"; Filename: "{app}\DeLector.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DeLector.exe"; Description: "{cm:LaunchProgram,DeLector}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientId = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

{ WebView2 运行时的客户端注册项在 HKLM 的两个视图下各有一份（32/64 位）。 }
function WebView2Installed: Boolean;
var
  Value: Cardinal;
  Key64: String;
  Key32: String;
begin
  Result := False;
  Key64 := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientId;
  Key32 := 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientId;
  if RegQueryDWordValue(HKLM, Key64, 'pv', Value) then
    Result := True
  else
    if RegQueryDWordValue(HKLM, Key32, 'pv', Value) then
      Result := True;
end;

{ 缺运行时才装 bootstrapper。**不阻断安装**：非管理员环境下 Evergreen bootstrapper
  可能装不上（它默认做机器级安装），此时应用自身仍会在启动时检测并给出官方下载入口。 }
procedure InstallWebView2IfMissing;
var
  ResultCode: Integer;
  SetupPath: String;
begin
  SetupPath := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  if WebView2Installed then
  begin
    Log('WebView2 运行时已存在，跳过 bootstrapper。');
    exit;
  end;
  if not FileExists(SetupPath) then
  begin
    Log('未找到 WebView2 bootstrapper（' + SetupPath + '），跳过；应用启动时会自行提示。');
    exit;
  end;
  Log('未检测到 WebView2 运行时，静默安装 bootstrapper…');
  if not Exec(SetupPath, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('bootstrapper 启动失败（Exec 返回 false）；不阻断安装，应用启动时仍会提示。')
  else if ResultCode <> 0 then
    Log('bootstrapper 退出码 ' + IntToStr(ResultCode) + '（非 0）；不阻断安装，应用启动时仍会提示。')
  else
    Log('WebView2 bootstrapper 安装完成。');
  DeleteFile(SetupPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallWebView2IfMissing;
end;
