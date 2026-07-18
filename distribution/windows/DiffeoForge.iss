; DiffeoForge evidence-only Windows CPU installer script.
; All variable paths and identities are supplied by a verified build plan.

#ifndef AppVersion
  #error AppVersion compiler define is required
#endif
#ifndef SourceCommit
  #error SourceCommit compiler define is required
#endif
#ifndef BundleDir
  #error BundleDir compiler define is required
#endif
#ifndef EvidenceDir
  #error EvidenceDir compiler define is required
#endif
#ifndef LicenseFile
  #error LicenseFile compiler define is required
#endif
#ifndef OutputDir
  #error OutputDir compiler define is required
#endif
#ifndef OutputBaseFilename
  #error OutputBaseFilename compiler define is required
#endif

[Setup]
AppId=DiffeoForge.WindowsCPU.x86_64
AppName=DiffeoForge
AppVersion={#AppVersion}
AppVerName=DiffeoForge {#AppVersion} (Windows CPU x86-64)
AppPublisher=DiffeoForge contributors
AppPublisherURL=https://github.com/heinjenny95/DiffeoForge
AppSupportURL=https://github.com/heinjenny95/DiffeoForge/issues
AppComments=Evidence build from source commit {#SourceCommit}
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\DiffeoForge
DefaultGroupName=DiffeoForge
DisableProgramGroupPage=auto
AllowNoIcons=yes
LicenseFile={#LicenseFile}
Uninstallable=yes
UninstallDisplayName=DiffeoForge {#AppVersion} (Windows CPU x86-64)
UninstallDisplayIcon={app}\DiffeoForge.exe
SetupLogging=yes
UninstallLogging=yes
ChangesAssociations=no
ChangesEnvironment=no
CloseApplications=yes
RestartApplications=no
RestartIfNeededByRun=no
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#EvidenceDir}\freeze-evidence.json"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#EvidenceDir}\freeze-evidence.sha256"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#EvidenceDir}\freeze-dependency-metadata.json"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#EvidenceDir}\freeze-dependency-metadata.sha256"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#EvidenceDir}\freeze-sbom.cdx.json"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#EvidenceDir}\freeze-sbom.cdx.sha256"; DestDir: "{app}\evidence"; Flags: ignoreversion
Source: "{#LicenseFile}"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\DiffeoForge"; Filename: "{app}\DiffeoForge.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\DiffeoForge"; Filename: "{app}\DiffeoForge.exe"; WorkingDir: "{app}"; Tasks: desktopicon
