#define AppName "ローカル文字起こしデスクトップアプリ"
#define AppPublisher "ローカル文字起こしデスクトップアプリ"
#define AppExeName "Local Whisper Transcriber.exe"
#define PreviousAppName "Local Whisper Transcriber"
#define AppVersion GetEnv("APP_VERSION")
#if AppVersion == ""
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{1F213281-64A6-4A66-A848-8D35AA730B2A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
LicenseFile=EULA.txt
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
OutputDir=..\dist\installer
OutputBaseFilename=LocalWhisperSetup-{#AppVersion}-x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップアイコンを作成する"

[Files]
Source: "..\dist\LocalWhisperTranscriber\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} を起動する"; Flags: nowait postinstall skipifsilent

[Code]
var
  ExistingInstallPromptShown: Boolean;

function ExistingInstallFound(InstallDir: string): Boolean;
begin
  Result :=
    FileExists(AddBackslash(InstallDir) + '{#AppExeName}') or
    FileExists(AddBackslash(InstallDir) + 'unins000.exe');
end;

function LaunchExistingUninstaller(InstallDir: string): Boolean;
var
  UninstallerPath: string;
  ResultCode: Integer;
begin
  Result := False;
  UninstallerPath := AddBackslash(InstallDir) + 'unins000.exe';

  if not FileExists(UninstallerPath) then
  begin
    MsgBox(
      '既存のインストールは見つかりましたが、アンインストーラーが見つかりませんでした。' + #13#10 +
      'Windows のアプリ一覧から手動でアンインストールしてください。',
      mbError,
      MB_OK
    );
    exit;
  end;

  if Exec(UninstallerPath, '', '', SW_SHOW, ewNoWait, ResultCode) then
  begin
    MsgBox(
      'アンインストーラーを起動しました。アンインストール完了後に、もう一度セットアップを実行してください。',
      mbInformation,
      MB_OK
    );
    Result := True;
  end
  else
  begin
    MsgBox(
      'アンインストーラーの起動に失敗しました。Windows のアプリ一覧から手動でアンインストールしてください。',
      mbError,
      MB_OK
    );
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  InstallDir: string;
  Choice: Integer;
begin
  Result := True;

  if (CurPageID <> wpSelectDir) or ExistingInstallPromptShown then
    exit;

  InstallDir := WizardDirValue;
  if not ExistingInstallFound(InstallDir) then
    exit;

  Choice := MsgBox(
    '既存のインストールが見つかりました。' + #13#10 + #13#10 +
    'はい: 既存ファイルを上書きしてインストールを続行します。' + #13#10 +
    'いいえ: 既存バージョンをアンインストールしてセットアップを終了します。' + #13#10 +
    'キャンセル: 何もせずセットアップを中止します。',
    mbConfirmation,
    MB_YESNOCANCEL
  );

  if Choice = IDYES then
  begin
    ExistingInstallPromptShown := True;
    exit;
  end;

  if Choice = IDNO then
  begin
    ExistingInstallPromptShown := True;
    LaunchExistingUninstaller(InstallDir);
    WizardForm.Close;
    Result := False;
    exit;
  end;

  Result := False;
end;
