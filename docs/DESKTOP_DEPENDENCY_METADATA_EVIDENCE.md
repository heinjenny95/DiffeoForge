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
manifest has passed independent verification. Its upload boundary contains the
two bundle-evidence files and these two dependency-metadata files, never the
unsigned executable directory.

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
