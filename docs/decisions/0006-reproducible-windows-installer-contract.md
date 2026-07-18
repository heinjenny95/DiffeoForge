# ADR 0006: Define a hash-bound Inno Setup 7 contract before building installers

- Status: Accepted design; no installer implemented or distributed
- Date: 2026-07-18
- Issue: [#158](https://github.com/heinjenny95/DiffeoForge/issues/158)

## Context

DiffeoForge now has an independently observed Windows one-directory freeze,
exact dependency metadata, and a deterministic CycloneDX 1.7 SBOM. Those
artifacts do not yet define how a user-facing installer is built, what it may
install or remove, or which exact toolchain and source evidence produced it.
Starting with an `.iss` script would make those boundaries implicit and could
turn a developer build into an apparent release before license and
redistribution review exists.

The current official Inno Setup releases considered were 6.7.3 and 7.0.2.
Version 7.0.2 is an immutable official GitHub release dated 13 July 2026. Its
x64 edition adds a native 64-bit setup option and extended-length-path support,
while retaining the documented console compiler, current-user/administrator
selection, silent install/uninstall, logs, and signatures. These properties
fit the existing x86-64 CPU bundle and its path-focused evidence better than a
new 32-bit installer contract.

## Decision

The first installer path will target `windows-x86_64-cpu` and use the official
x64 Inno Setup 7.0.2 asset from immutable release tag `is-7_0_2`. The exact
17,020,192-byte installer has SHA-256
`5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1`.
Before that tool is executed, a future build must verify the GitHub release
attestation, exact hash, and valid Authenticode publisher `Pyrsys B.V.`. An
unpinned `latest`, `winget` resolution, or other package-manager lookup is not
an accepted release build input.

The exact machine contract is
`distribution/windows/installer-contract-v0.1.json`. The console compiler
`ISCC.exe` will receive an explicit script, application version, source commit,
input roots, and output name. The application version must match
`pyproject.toml`; a release candidate may not retain a development version.
`DiffeoForge.WindowsCPU.x86_64` is the stable application ID so upgrades share
one uninstall identity without coupling it to a display version.

The setup executable will be x64, allow `x64compatible` systems, and make no
native Arm64 claim. `MinVersion=10.0.17763` rejects systems older than Windows
10 version 1809, the current Qt 6.11 Windows platform floor. This minimum gate
does not claim that every later Windows build has been tested; the advertised
support matrix still requires clean-VM evidence. Installation defaults to
non-administrative current-user mode with `PrivilegesRequired=lowest`. The
documented dialog and command-line overrides may select administrator or
current-user mode explicitly. The automatic Program Files constant chooses the
matching per-user or common location. A Start Menu shortcut is required; a
desktop shortcut is opt-in and unchecked. No file association, PATH
modification, service, scheduled task, automatic launch, update check,
telemetry, download, or external Deformetrica installation is permitted by
this first contract.

Before compilation, the complete bundle must pass its full verifier and the
six downloaded evidence files must pass exact external-hash and deterministic
SBOM reconstruction checks. The installed application tree contains the
unchanged verified bundle and offline copies of the six evidence files. User
projects, meshes, landmarks, and results remain outside the application
directory. Uninstall may remove application files, shortcuts, and uninstall
registration only; it has no recursive project-data action or
`[UninstallRun]` command.

The future build wrapper must refuse existing output, symbolic input/output
paths, output inside the bundle or source-evidence directory, and any compiler
failure. It must create a setup SHA-256 sidecar and an installer-evidence
document plus sidecar bound to source, script, toolchain, freeze, dependency,
SBOM, bundle inventory, and setup hashes.

Inno Setup output is not claimed to rebuild byte for byte. Reproducibility here
means the same documented process and exact inputs, with every concrete output
independently hashed and recorded. A byte-identical claim requires separate
evidence and may not be inferred from this contract.

## Consequences

- the installer design is reviewable before any executable is produced;
- toolchain authenticity is checked independently before code execution;
- current-user and administrator observations remain distinct;
- application files and research projects have an explicit uninstall boundary;
- the exact frozen runtime and its SBOM remain traceable through the installer;
- a future evidence build can fail closed on altered inputs or accidental
  overwrite; and
- no installer, license compatibility decision, redistribution approval,
  signature, clean-machine result, or scientific claim exists merely because
  this ADR is accepted.

## Rejected for the first installer contract

- Inno Setup 6.7.3: still supported, but the 32-bit toolchain does not provide
  the selected native x64 setup and extended-length-path baseline;
- an unpinned `winget` or latest-version installation;
- PyInstaller one-file output or runtime extraction into temporary folders;
- a combined CPU/CUDA installer with implicit runtime selection;
- installing Python, pip packages, Deformetrica, or scientific data on the
  user's machine;
- automatic post-install launch or network activity;
- uninstall code that searches for or removes projects; and
- calling repeatable commands or a stable filename a byte-deterministic build.

## Primary references

- [Official Inno Setup downloads](https://jrsoftware.org/isdl.php)
- [Official download verification](https://jrsoftware.org/isdl-verify.php)
- [Inno Setup 7 revision history](https://jrsoftware.org/files/is7-whatsnew.htm)
- [Console compiler execution](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
- [Setup command-line parameters](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)
- [Uninstaller command-line parameters](https://jrsoftware.org/ishelp/topic_uninstcmdline.htm)
- [PrivilegesRequired](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
- [PrivilegesRequiredOverridesAllowed](https://jrsoftware.org/ishelp/topic_setup_privilegesrequiredoverridesallowed.htm)
- [Architecture identifiers](https://jrsoftware.org/ishelp/topic_archidentifiers.htm)
- [SetupArchitecture](https://jrsoftware.org/ishelp/topic_setup_setuparchitecture.htm)
- [MinVersion](https://jrsoftware.org/ishelp/topic_setup_minversion.htm)
- [Qt 6.11 supported Windows platforms](https://doc.qt.io/qt-6/supported-platforms.html)
