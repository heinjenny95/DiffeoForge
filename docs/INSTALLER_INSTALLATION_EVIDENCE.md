# Isolated Windows installer installation evidence

Status: **real lifecycle and retained-artifact integrity observations accepted**

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

The `Windows installer installation evidence` workflow is a path-scoped pull
request gate for installer-relevant changes and can also be started manually
from an exact reviewed commit already available on the default branch. A
successful run uploads exactly eight files:

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

The exact eight-file artifact remains integrity-verifiable after download with
`installer_installation_evidence.py verify-retained`, an externally recorded
canonical-evidence SHA-256, and the versioned schema. This checks every retained
file hash, lifecycle binding, installed inventory summary, runner identity,
zero-endpoint observation, and unchanged sentinel. It deliberately does not
claim to reconstruct the deleted setup, frozen bundle, or toolchain. Full
source/setup reconstruction is performed only on the live runner before its
temporary inputs are destroyed.

## First accepted real observation

GitHub Actions run
[`29648460007`](https://github.com/heinjenny95/DiffeoForge/actions/runs/29648460007)
completed the full lifecycle on July 18, 2026. It observed the GitHub-generated
pull-request merge commit
`e0fdd4a776c3f1db68baff656c254d3f8cc3b979`; this is evidence for the reviewed
PR state, not yet for a merged release commit.

- Canonical installation-evidence SHA-256:
  `a02071c3e194308ee87639c58202be856fe4299b87109b56e6c5c81009ebb96a`.
- Unsigned setup: 255,996,272 bytes; SHA-256
  `b2a32f4c55478f5a9341d66172b1f627872782c6aa65e47232434c31d75f1e39`.
- Installed tree before launch: 2,674 files and 680,081,753 bytes.
- Install, installed smoke, and uninstall exit codes: `0`, `0`, and `0`.
- Desktop-process endpoints sampled during smoke: `0`.
- Application root, Start Menu shortcut, and uninstall registration after
  uninstall: absent.
- External project sentinel: 29 bytes and unchanged SHA-256
  `7edd24f8fbb194ab335dfeb47ad69cc9794ef1038ae9a5dabb5dbadbb9bf91c0`.
- Uploaded artifact `8430908387`: exactly eight evidence/log files and no
  executable.

The downloaded eight-file artifact passed the new retained-integrity verifier
against the externally recorded canonical digest. The verifier wording and
contract correction were added after that run.

## Accepted refined observation

GitHub Actions run
[`29649381912`](https://github.com/heinjenny95/DiffeoForge/actions/runs/29649381912)
then repeated the complete lifecycle from the refined PR state and invoked both
the full live-input verifier and retained-artifact verifier before upload. It
observed GitHub-generated pull-request merge commit
`a3dcd09c087b9cb5dd57eb4ea02310d2316d5116`.

- Canonical installation-evidence SHA-256:
  `b2baa429c01f83e4c6636712406ad2e9e5e684798b6336291fc55c890401b952`.
- Unsigned setup: 255,991,834 bytes; SHA-256
  `56f9c84db0c7845df44950fa7b66100ff130cfe2c2ebba0c64c4e7330c954c20`.
- Installed tree before launch: 2,674 files and 680,081,753 bytes.
- Install, installed smoke, and uninstall exit codes: `0`, `0`, and `0`.
- Desktop-process endpoints sampled during smoke: `0`.
- Application root, Start Menu shortcut, and uninstall registration after
  uninstall: absent.
- External project sentinel: 29 bytes and unchanged SHA-256
  `7edd24f8fbb194ab335dfeb47ad69cc9794ef1038ae9a5dabb5dbadbb9bf91c0`.
- Uploaded artifact `8431172545`: exactly eight evidence/log files and no
  executable.
- The downloaded artifact independently passed `verify-retained` against the
  canonical digest above.

## Explicit nonclaims

Even a successful observation does not establish administrator-mode behavior,
host-wide network isolation, Windows Defender clearance, Authenticode signing,
license compatibility, redistribution approval, numerical correctness on the
installed artifact, scientific validity, usability, production suitability,
or public-release readiness. Producing a private tester handoff is a separate
gate after this observation succeeds.
