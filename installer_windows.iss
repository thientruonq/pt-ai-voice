; ──────────────────────────────────────────────────────────────────────────────
; PT AI Voice — Inno Setup Installer Script
; Tạo file installer .exe chuyên nghiệp cho Windows
;
; Yêu cầu: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Cách dùng: Mở file này bằng Inno Setup Compiler → Build
; ──────────────────────────────────────────────────────────────────────────────

#define MyAppName "PT AI Voice"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "PT"
#define MyAppExeName "PT AI Voice.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=PT_AI_Voice_v{#MyAppVersion}_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
SetupLogging=yes

; Uncomment nếu có icon riêng:
; SetupIconFile=app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy toàn bộ thư mục output từ PyInstaller
Source: "dist\PT AI Voice\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Nếu bạn có ffmpeg.exe, bỏ comment dòng dưới:
; Source: "ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Gỡ cài đặt {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Chạy {#MyAppName}"; Flags: nowait postinstall skipifsilent
