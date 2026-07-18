# Isolated Windows installer installation evidence

Status: **implemented evidence workflow; real observation pending**

This developer-only workflow takes the exact unsigned output of the
[engineering installer build](INSTALLER_BUILD_EVIDENCE.md) through one complete
current-user lifecycle on an ephemeral GitHub-hosted Windows runner:

```text
verified setup
  -> silent current-user install
  -> exact installed-file inventory
  -> Start Menu and uninstall-registration verification
  -> installed DiffeoForge.exe --smoke
  -> desktop-process network sampling
  -> silent uninstall
  -> application/shortcut/registration absence checks
  -> external project-sentinel verification
```

The machine boundary is
`distribution/windows/installer-installation-evidence-contract-v0.1.json`.
The wrapper refuses to run unless GitHub Actions identifies an ephemeral
Windows X64 runner. It therefore cannot be used accidentally to install the
unsigned engineering setup on a developer's normal Windows account.

## Exact prerequisites

Before setup execution, the observer reconstructs an externally hash-bound
`installer-build-evidence.json`. That reconstruction re-verifies the exact
source, frozen bundle, six-file dependency/SBOM boundary, installer plan,
portable Inno toolchain, compiler observation, setup bytes, and all sidecars.
The build must remain explicitly non-release and the setup must have Windows
Authenticode status `NotSigned`.

The workflow creates every input from one clean source commit on the same
ephemeral runner. It independently authenticates Inno Setup through the pinned
release attestation, Authenticode publisher, detached ISSig signature, and
portable compiler-probe evidence before compiling DiffeoForge.

## Installation boundary

The exact setup arguments select:

- silent current-user installation;
- a new runner-temporary path containing spaces and non-ASCII text;
- the normal DiffeoForge Start Menu group;
- no desktop shortcut; and
- an explicit install log outside the application directory.

Before application launch, the Python verifier inventories every installed
file. Every frozen-bundle file, all six dependency/SBOM evidence copies, and
`LICENSE.txt` must match their retained sources byte-for-byte. Any extra file
outside the expected Inno uninstaller set is fatal. The Start Menu shortcut
must target the exact installed `DiffeoForge.exe`, and the current-user
uninstall registration must bind the exact installed uninstaller.

## Installed smoke and network scope

The installed desktop executable runs only with `--smoke`. While that process
is alive, the wrapper samples TCP connections and UDP endpoints owned by its
exact process ID. Any observed endpoint fails the observation.

This is intentionally a **desktop-process-specific observation**. It is not a
host-wide offline or firewall-isolation experiment, does not cover unrelated
runner processes, and does not prove that every later GUI path is network-free.

## Uninstall and project preservation

An independently hashed sentinel resides in a project directory outside the
install and evidence roots. Its exact path, byte count, and SHA-256 must remain
unchanged after install, installed smoke, and uninstall.

The Inno uninstaller runs silently with an explicit external log. Success
requires all three product-owned boundaries to be absent afterward:

- application directory;
- Start Menu shortcut; and
- current-user uninstall registration.

The project sentinel must still match exactly.

## Evidence-only GitHub workflow

Run the manual `Windows installer installation evidence` workflow from an exact
reviewed commit. A successful run uploads exactly eight files:

- `install.log`;
- `installed-file-inventory.json`;
- `installer-install-observation.json`;
- `installed-smoke-observation.json`;
- `uninstall.log`;
- `installer-uninstall-observation.json`;
- `installer-installation-evidence.json`; and
- `installer-installation-evidence.sha256`.

The setup executable, frozen application bundle, toolchain, and intermediate
build files are deliberately not uploaded. The artifact is observation
evidence, not a private alpha download.

## Explicit nonclaims

Even a successful observation does not establish administrator-mode behavior,
host-wide network isolation, Windows Defender clearance, Authenticode signing,
license compatibility, redistribution approval, numerical correctness on the
installed artifact, scientific validity, usability, production suitability,
or public-release readiness. Producing a private tester handoff is a separate
gate after this observation succeeds.
