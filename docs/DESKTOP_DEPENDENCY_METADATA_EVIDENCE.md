# Frozen dependency metadata evidence

Status: **deterministic review input, not a license inventory, SBOM, approval,
or release artifact**

The Windows freeze records the exact installed Python distribution names and
versions used by the builder. `desktop-dependency-metadata-evidence-v0.1`
turns that package map into a separately hash-bound review input without
claiming to interpret license compatibility or redistribution rights.

Creation accepts a verified schema-v0.3 bundle and requires the independently
recorded SHA-256 of its complete `freeze-evidence.json`. It fails closed if the
manifest differs, the exact bundle inventory no longer verifies, an installed
distribution is absent, its normalized name or version differs from the freeze
manifest, its installed file records are unavailable, or its exact `METADATA`
file cannot be located and read.

For every sorted runtime distribution, the evidence records:

- normalized distribution name and exact version;
- exact installed `METADATA` byte count and SHA-256;
- Core Metadata version, `License-Expression`, legacy `License`, license
  classifiers, `License-File` declarations, and `Requires-Dist` values;
- exact byte counts and SHA-256 hashes for declared or conventionally named
  installed license-related files;
- declared license files that could not be matched to an installed file; and
- explicit observations for absent, legacy, or simultaneously present fields,
  while leaving every package `unreviewed`.

The complete sorted package array has its own aggregate SHA-256. The evidence
also binds the freeze-manifest SHA-256, source commit, target, and bundle
inventory SHA-256. It writes exactly `freeze-dependency-metadata.json` and
`freeze-dependency-metadata.sha256` into an existing real directory outside
the bundle. Existing targets and symbolic targets are refused. Writing inside
the bundle is forbidden because it would invalidate the already sealed bundle
inventory.

## Reproduce and verify

First verify the bundle and obtain the exact full-file manifest SHA-256. The
output directory must already exist and must be outside the bundle.

```powershell
python tools/desktop_bundle_evidence.py verify C:\evidence\DiffeoForge
$freezeSha = (Get-FileHash C:\evidence\DiffeoForge\freeze-evidence.json -Algorithm SHA256).Hash.ToLowerInvariant()
New-Item -ItemType Directory C:\evidence\review | Out-Null
python tools/desktop_dependency_metadata_evidence.py create C:\evidence\DiffeoForge `
  --expect-freeze-evidence-sha256 $freezeSha `
  --output-directory C:\evidence\review
python tools/desktop_dependency_metadata_evidence.py verify `
  C:\evidence\review\freeze-dependency-metadata.json `
  --expect-freeze-evidence-sha256 $freezeSha
```

Verification of a downloaded pair is environment-independent. It revalidates
the schema and exact sidecar, requires the external freeze-manifest hash,
checks unique sorted package names and count, and recomputes the package-set
hash. It does not need the executable bundle or installed packages because it
verifies the recorded evidence rather than recreating it.

The manual clean-runner workflow creates this pair only after the exact bundle
manifest has passed independent verification. It then creates the deterministic
CycloneDX pair from both externally bound source documents. The configured
upload boundary contains these three JSON documents and their three exact
sidecars, never the unsigned executable directory. The first independently
inspected observation below predates that six-file integration and remains a
historical four-file artifact. The later accepted six-file observation is
documented in
[Windows one-directory freeze evidence](WINDOWS_FREEZE_EVIDENCE.md).

## First clean-runner observation

[Workflow run 29635525566](https://github.com/heinjenny95/DiffeoForge/actions/runs/29635525566)
successfully created and verified the first four-file artifact on a fresh
GitHub-hosted `windows-latest` runner on 18 July 2026. It was manually
dispatched from clean merge commit
`ac10b0953f6c4ad11bd98001694726d6ed870d2d`. The job completed in 7 minutes
59 seconds: checkout took 17 seconds, Python setup 12 seconds, builder
installation 1 minute 11 seconds, complete freeze and verification 6 minutes
10 seconds, and upload 3 seconds. The recorded builder used Python 3.12.10,
PyInstaller 6.21.0, CPU-only Torch, and
`Windows-2025Server-10.0.26100-SP0`.

The independently downloaded artifact contained exactly:

- `freeze-evidence.json`: 518,358 bytes, SHA-256
  `ab0aba54775fc7d8b1f19893fdc119c0967ba28e3177b2886b2c5e3894c2075f`;
- `freeze-evidence.sha256`: 87 bytes, SHA-256
  `9ca58ab0131015693fbfc8ed39f9dd0e4a7c88f0f85da80608d777e2b11e8ad5`;
- `freeze-dependency-metadata.json`: 84,920 bytes, SHA-256
  `832ee01d497c76cbc5e926a1b4e343eb59ae5ae07bf455671c6b4becda9954b5`;
  and
- `freeze-dependency-metadata.sha256`: 98 bytes, SHA-256
  `eb25e7214968198d83cae19c76cd85e7d6170174829241d6d1d55099873069d0`.

Both sidecars matched byte for byte. The freeze manifest recorded 2,657 files,
671,225,043 bytes, and inventory SHA-256
`bd9322e5a32332d95b0bf3ba179fd10ae69f2caf2278706a8b8e815f1b7c956d`.
The dependency evidence bound that exact manifest and recorded 27 unique sorted
packages with package-set SHA-256
`4f96da73ff8e01d2363dfa23741f22cd1a4eb8908b31dac3e137f0931d6d88ed`.
All 27 had at least one installed license-related file; 152 such files were
hashed in total. Fourteen distributions exposed `License-Expression`, eleven
exposed legacy `License`, and no declared `License-File` remained unresolved.

The GitHub artifact was ID `8427033855`, 604,065 bytes, with archive digest
`sha256:63cadebb1839e1fa6129c786130fe4e5e3c300fd13624a1862443bddf2f987b0`.
Its expiry was 1 August 2026. After download, both JSON documents were
schema-validated, both source-commit bindings were checked, the freeze sidecar
was compared as exact bytes, and the dependency verifier recomputed its
canonical JSON, external source hash, package count/order, and package-set
hash.

This observation does not change the review boundary. The evidence itself
retains `license_inventory`, `license_compatibility_review`,
`redistribution_approval`, and `sbom` as missing release gates. The counts above
describe metadata and file presence, not license identity, compatibility, or
permission.

## Interpretation boundary

Core Metadata license fields are optional and have changed over time. Starting
with Core Metadata 2.4, `License-Expression` contains an SPDX expression for
the particular distribution archive containing that metadata; it does not by
itself describe every related project file or grant redistribution approval.
Legacy `License` text and license classifiers can be incomplete or ambiguous.
File presence and SHA-256 prove only which bytes were installed in this builder
environment.

Therefore this evidence deliberately retains all of the following release
gates:

- a reviewed third-party license inventory;
- license-compatibility review;
- redistribution approval; and
- an actual versioned SPDX or CycloneDX SBOM.

It also says nothing about installer behavior, signatures, antivirus results,
clean-machine execution, network behavior, numerical equivalence, atlas
quality, or biological interpretation.

Primary metadata references:

- [PyPA Core Metadata specification](https://packaging.python.org/en/latest/specifications/core-metadata/)
- [PyPA License Expression specification](https://packaging.python.org/en/latest/specifications/license-expression/)
- [Python 3.12 `importlib.metadata`](https://docs.python.org/3.12/library/importlib.metadata.html)
