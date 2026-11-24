#ifndef AppVersion
  #define AppVersion "0.7.4"
#endif
#ifndef ReleaseAppId
  #define ReleaseAppId "{{AC636DF7-E24E-44E9-83CE-B93FD8E3B962}"
#endif
#ifndef ReleaseName
  #define ReleaseName "MeisterCode"
#endif
#ifndef OutputName
  #define OutputName "Meister-IA-IDE-" + AppVersion + "-Setup"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Meister IA IDE"
#endif
[Setup]
AppId={#ReleaseAppId}
AppName={#ReleaseName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\Meister IA IDE
DefaultGroupName={#ReleaseName}
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=MeisterIAIDE.Desktop
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\Studio de Media.exe
SetupLogging=yes
VersionInfoVersion={#AppVersion}
[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
[Tasks]
Name: "desktopicon"; Description: "Criar atalho no ambiente de trabalho"; Flags: unchecked
[Dirs]
; A app guarda tudo na sua pasta (Configuracao, Conversas, Projectos, Ferramentas, Temp): os utilizadores têm de poder escrever nela.
Name: "{app}"; Permissions: users-modify
[InstallDelete]
; restos de uma versão anterior: bibliotecas antigas e o marcador que mandava os dados para AppData
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\studio-install.json"
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; com este marcador a app trabalha só dentro da sua pasta, sem nada em AppData
Source: "portable.json"; DestDir: "{app}"; DestName: "meistercode-portable.json"; Flags: ignoreversion
[Icons]
Name: "{group}\{#ReleaseName}"; Filename: "{app}\Studio de Media.exe"
Name: "{autodesktop}\{#ReleaseName}"; Filename: "{app}\Studio de Media.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Studio de Media.exe"; Description: "Abrir Meister IA IDE"; Flags: nowait postinstall skipifsilent
