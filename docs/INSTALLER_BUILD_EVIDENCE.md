# Engineering-only Windows installer build evidence

This developer-only workflow compiles one exact, explicitly non-release
DiffeoForge installer plan with the previously authenticated portable Inno
Setup toolchain. The setup executable is hashed and retained privately for
later installation tests. It is not executed, signed, uploaded, distributed,
or described as usable by this workflow.

## Required retained inputs

Before `ISCC.exe` can run, the wrapper offline-reconstructs both:

- a canonical `installer-build-plan.json` plus an externally supplied plan
  SHA-256; and
- canonical portable Inno toolchain evidence plus an externally supplied
  evidence SHA-256.

The plan reconstruction rechecks the complete frozen bundle, its exact freeze
manifest, the six-file dependency-metadata/SBOM boundary, project and runtime
version, installer script, license, source commit, output path, and exact
nine-argument compiler vector. The engineering wrapper rejects any plan with
`release_candidate: true`.

The portable evidence reconstruction rechecks the authenticated installer,
installed 132-file inventory, four critical Authenticode observations, and the
successful fixed compiler probe. The compiler program must be the exact
`ISCC.exe` already bound by that evidence.

## Windows observation

Create a non-executing plan in a new empty plan/output directory and create a
second new empty evidence directory. From an exact clean checkout, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\observe_installer_build.ps1 `
  -Plan C:\absolute\plan-output\installer-build-plan.json `
  -ExpectedPlanSha256 <64-lowercase-hex> `
  -PortableEvidence C:\absolute\portable-evidence\inno-portable-toolchain-evidence.json `
  -ExpectedPortableEvidenceSha256 <64-lowercase-hex> `
  -ProjectFile C:\absolute\DiffeoForge\pyproject.toml `
  -EvidenceOutputDirectory C:\absolute\new-empty-build-evidence `
  -ObserverSourceCommit <40-lowercase-hex> `
  -Python C:\absolute\DiffeoForge\.venv\Scripts\python.exe
```

The wrapper runs only `ISCC.exe` with the plan's exact argument array. It
requires Windows Authenticode status `NotSigned`, records that open gate, and
does not invoke the resulting setup. Existing outputs are never overwritten.

After a successful build, the plan/output boundary contains exactly:

- `installer-build-plan.json`;
- `installer-build-plan.sha256`;
- the exact setup filename declared by the plan; and
- `<setup filename>.sha256`.

The separate build-evidence boundary contains exactly:

- `installer-compiler-observation.json`;
- `installer-build-evidence.json`; and
- `installer-build-evidence.sha256`.

## Offline reconstruction

Retain all referenced source, bundle, six-file evidence, plan, portable
toolchain, setup, raw observation, and sidecars. Then verify without executing
the compiler or setup:

```powershell
python tools\installer_build_evidence.py verify `
  C:\absolute\build-evidence\installer-build-evidence.json `
  --expect-evidence-sha256 <64-lowercase-hex>
```

The external digest is an independent trust anchor. The verifier rejects
changed bundle files, source evidence, plan bytes, toolchain files, compiler
observations, setup bytes, sidecars, extra files, symbolic paths, and changed
source contracts.

## First accepted private engineering observation

One Windows observation completed successfully on 18 July 2026 at
`2026-07-18T13:20:51.6445579Z`. It used observer source commit
`58dea1429129d5d0332630596ddb0f2c09de32ec`, the frozen CPU bundle from source
commit `b821e20d09c9ce349df225a4b598193686d9468c`, and an explicitly non-release
`0.0.0.dev0` plan.

Retained trust anchors:

- installer plan SHA-256:
  `1f0c07b4093175176bd2fa3c0aa2ada9ef76addf358fbcb4effc741e539f0936`;
- frozen-bundle inventory SHA-256:
  `c2de820ba18da9aa8157fa282547f528cc0fb0c018ea23e5e483dc15ea83eef9`;
- freeze-evidence SHA-256:
  `e2613f59357da1c79685c4059dbfc16babc71918a170aef95c8c70be56f5dd5a`;
- dependency-evidence SHA-256:
  `781f6176cb78f67eed4299392e035cfffa3ecec7f6e346757c3b09d5559775c7`;
- CycloneDX SBOM SHA-256:
  `62b10fb784ed6e029160ebc73c1075014901148f113e63e172e8d41a6db59b6f`;
- portable-toolchain evidence SHA-256:
  `027c32e9eec207401401d819e986cad081b0661c8158be008d4b744abf084444`;
- resulting 259,161,052-byte setup SHA-256:
  `da6c23df9d9ac1edcc313d7adb813701d0f2e62582ddb811b2c1e8ad42c0e132`;
  and
- final build-evidence SHA-256:
  `bce1f9b6130cf9f55d69572fa60d2e1645c1f6ea0125d0e805f36a7851b95800`.

The wrapper and an independent Windows check both observed Authenticode status
`NotSigned`. The setup was not executed, uploaded, distributed, or released.
The private retained files are engineering evidence, not a downloadable
installer.

An earlier successful compilation exposed that the first evidence schema did
not record the setup's Authenticode status. That result was not accepted as
the observation. The contract, schema, wrapper, verifier, and tests were
tightened to require `NotSigned`, and the complete observation was repeated.
The two compilation outputs had different hashes, but their absolute input and
output paths and plan bytes also differed; this is therefore not a controlled
compiler-determinism experiment and supports no determinism conclusion.

## Explicit nonclaims

This slice does not establish setup or uninstaller execution, a usable
installer, Authenticode for DiffeoForge outputs, license compatibility,
redistribution approval, bit-for-bit deterministic compiler output, clean-VM
behavior, Defender status, network isolation, project preservation, numerical
correctness, scientific validity, or production suitability. No version or
release-candidate decision is made here.
