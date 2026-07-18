# Reproducible Windows installer build contract

Status: **accepted design plus one verified private engineering build; no
installer has been executed, signed, distributed, or released**

The first DiffeoForge installer was deliberately specified before its first
private engineering compilation.
The human-readable decision is
[ADR 0006](decisions/0006-reproducible-windows-installer-contract.md); the exact
machine contract is
`distribution/windows/installer-contract-v0.1.json`.

The first implementation slice added the exact offline script
`distribution/windows/DiffeoForge.iss` and a deterministic plan generator. It
does not download or run Inno Setup and cannot create an installer by itself.
The later, separately bounded engineering workflow has now compiled one exact
non-release plan without executing the resulting setup.

## What is fixed

- target: Windows x86-64 CPU, separate from CUDA, Arm64-native, Linux, macOS,
  containers, and HPC installation routes;
- tool: official immutable Inno Setup 7.0.2 x64 release asset, verified by
  GitHub release attestation, exact SHA-256, and Authenticode publisher before
  execution;
- compiler: noninteractive `ISCC.exe` with explicit source, version, input, and
  output parameters;
- input: one fully verified frozen bundle plus the exact six-file freeze,
  dependency-metadata, and CycloneDX evidence boundary;
- default scope: non-administrative current user, with explicit current-user or
  administrator override;
- installed behavior: offline application files and evidence only, no Python
  resolver, Deformetrica installation, network action, telemetry, service,
  scheduled task, or automatic launch; and
- uninstall: application files, shortcuts, and uninstall registration only,
  never user-selected projects or research data.

## Toolchain identity

The selected official asset is `innosetup-7.0.2-x64.exe`, 17,020,192 bytes,
SHA-256
`5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1`,
from immutable release tag `is-7_0_2` in `jrsoftware/issrc`. Each build must
run the official release-specific
`gh release verify-asset is-7_0_2 <asset> --repo jrsoftware/issrc --format json`
check with the positional tag fixed rather than resolving `latest`,
not the generic artifact-attestation command, and validate the
Authenticode publisher `Pyrsys B.V.` before executing the downloaded tool. The
hash check is necessary but does not replace the authenticity checks.
The implemented, still non-executing observation and offline reconstruction
workflow is documented in
[Inno Setup toolchain authenticity evidence](INNO_TOOLCHAIN_EVIDENCE.md).
The independent built-in signature check and its verifier trust chain are
specified in [Inno Setup ISSigTool signature evidence](INNO_SIGNATURE_EVIDENCE.md).
Before this contract permits any DiffeoForge installer build, a separate
[portable toolchain and compiler-probe observation](INNO_PORTABLE_TOOLCHAIN_EVIDENCE.md)
must establish that the authenticated installer prepares the exact expected
compiler inventory and that `ISCC.exe` can compile the fixed payload-free probe.
That observation alone does not authorize a DiffeoForge installer build,
signing, redistribution, or release. A separately bounded workflow is
documented in
[engineering-only installer build evidence](INSTALLER_BUILD_EVIDENCE.md). It
accepts only a `release_candidate: false` plan, produces an unsigned setup in a
private local evidence boundary, and never executes or distributes that setup.
The first accepted observation and its external trust anchors are recorded
there.
The next evidence-only gate is the
[isolated installer installation workflow](INSTALLER_INSTALLATION_EVIDENCE.md).
It is restricted to an ephemeral GitHub-hosted Windows runner and verifies one
current-user install, installed desktop smoke, uninstall, and external project
sentinel without uploading the setup. Its first real observation is still
pending.

## Required build inputs

The wrapper must receive rather than infer:

- exact lowercase source commit;
- application version matching `[project].version` in `pyproject.toml`;
- installer-script hash;
- full frozen bundle and its exact external freeze-manifest hash;
- exact dependency-evidence and SBOM hashes; and
- existing real output directory outside all inputs.

The complete bundle verifier and downloaded six-file SBOM verifier must pass
before compilation. Existing output, symbolic or junction inputs, output under
an input root, mismatched source/version/bundle bindings, nonzero compiler exit,
or post-build verification failure are fatal.

## Create and verify a non-executing build plan

Install the source environment including the separately scoped SBOM builder,
then provide a fully verified bundle, an exact six-file downloaded evidence
directory, three hashes obtained independently from that download, and a new
empty output directory outside the repository and both inputs:

```powershell
python tools/desktop_installer_plan.py create `
  C:\exact\DiffeoForge `
  C:\exact\six-file-evidence `
  --project-file C:\source\DiffeoForge\pyproject.toml `
  --output-directory C:\new-empty\installer-plan `
  --expect-freeze-evidence-sha256 <64-hex> `
  --expect-dependency-evidence-sha256 <64-hex> `
  --expect-sbom-sha256 <64-hex>
```

The command writes only `installer-build-plan.json` and
`installer-build-plan.sha256`. The plan fixes the future setup filename and
the exact non-shell `ISCC.exe` argument vector while recording
`execution_authorized: false`. Verify it against a separately retained plan
hash with:

```powershell
python tools/desktop_installer_plan.py verify `
  C:\new-empty\installer-plan\installer-build-plan.json `
  --expect-plan-sha256 <64-hex>
```

Verification rechecks the complete bundle, all three external evidence hashes,
the deterministic SBOM mapping, source commit, runtime/project version, script,
contract, project metadata, license, future output path, and compiler
arguments. Absolute paths are reviewed inputs; identical plan bytes require
the same exact paths as well as identical file content. Existing entries,
symbolic or junction paths, extra evidence, altered inputs, and release-candidate
plans for development or local versions fail closed.

## Install and uninstall boundary

The future script will use a stable application ID, `SetupArchitecture=x64`,
and `x64compatible` for both the allowed architecture and 64-bit install mode.
`MinVersion=10.0.17763` enforces Windows 10 version 1809, the current Qt 6.11
platform floor, or later. This minimum check is not a tested support claim;
specific Windows versions remain gated by later clean-VM evidence. The
installer defaults to `{autopf}\DiffeoForge` in current-user mode; Inno Setup
resolves the automatic Program Files constant for the chosen current-user or
administrative mode. It creates a Start Menu shortcut. A desktop shortcut may
be offered but is unchecked by default.

No project default is located under `{app}`. The application continues to ask
for a user-selected project root. The uninstaller has no code or command that
recursively discovers projects, meshes, landmarks, atlas results, or PCA
outputs. Preservation still requires direct clean-VM install/uninstall
observation before a usable-installer claim.

## Output evidence, not deterministic bytes

A later, separately authorized build produces a setup executable, its exact
SHA-256 sidecar, and an installer-evidence document plus sidecar. That document
binds the output to the
source commit, application version, installer script, verified Inno Setup
asset, freeze manifest, dependency evidence, SBOM, bundle inventory, and setup
hash.

This contract does not claim that two Inno Setup compilations are byte
identical. It defines a reproducible procedure whose concrete outputs are
independently hashed. Any stronger build-determinism claim needs its own
experiment and acceptance criterion.

## Gates before anyone receives an installer

No executable will be uploaded or described as usable until later slices and
named reviewers cover at least:

- implementation and non-overwriting build evidence;
- reviewed third-party license inventory, compatibility decision, and
  redistribution approval;
- current-user and administrator silent install, launch, public smoke, exit,
  and uninstall on clean Windows VMs without Python or developer tools;
- exact install/uninstall logs and preservation of user projects;
- spaces, non-ASCII names, and long paths;
- Authenticode on installer, uninstaller, and application executables;
- Windows Defender and no-network observations; and
- CPU numerical validation on the exact installed artifact.

Signing, legal review, clean-machine behavior, numerical equivalence, atlas
quality, PCA interpretation, and biological validity are independent gates;
this design satisfies none of them by itself.
