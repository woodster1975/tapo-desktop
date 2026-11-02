#ifndef AppVersion
  #define AppVersion "0.7.3"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\windows\TapoDesk"
#endif
#ifndef OutputPath
  #define OutputPath "..\dist\installers"
#endif

[Setup]
#ifdef ValidationInstall
AppId=TapoDesk.Desktop.Validation
AppName=Tapo Desk installer verification
#else
AppId=TapoDesk.Desktop
AppMutex=TapoDesk.Desktop
AppName=Tapo Desk
#endif
AppVersion={#AppVersion}
AppPublisher=Tapo Desk
AppVerName=Tapo Desk {#AppVersion}
DefaultDirName={localappdata}\Programs\Tapo Desk
DefaultGroupName=Tapo Desk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputPath}
OutputBaseFilename=TapoDesk-{#AppVersion}-Setup-x64
SetupIconFile=..\assets\tapo-desk.ico
UninstallDisplayIcon={app}\TapoDesk.exe
VersionInfoVersion={#AppVersion}
#ifdef ValidationInstall
Compression=none
SolidCompression=no
#else
Compression=lzma2/normal
SolidCompression=yes
#endif
WizardStyle=modern
CloseApplications=no
RestartApplications=no
InfoBeforeFile=INSTALL-NOTES.txt

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Tapo Desk"; Filename: "{app}\TapoDesk.exe"; WorkingDir: "{app}"; AppUserModelID: "TapoDesk.Desktop"
Name: "{autodesktop}\Tapo Desk"; Filename: "{app}\TapoDesk.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "TapoDesk.Desktop"

[Run]
Filename: "{app}\TapoDesk.exe"; Description: "Launch Tapo Desk"; Flags: nowait postinstall skipifsilent

; No uninstall-delete rules touch user settings, credentials, caches or clips.
