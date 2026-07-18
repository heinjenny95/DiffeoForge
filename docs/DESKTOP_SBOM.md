# Deterministic Windows post-build SBOM

Status: **implemented evidence tool; not a release, license decision, or uploaded
clean-runner observation**

DiffeoForge can deterministically convert one exact Windows freeze manifest and
its separately generated dependency-metadata evidence into CycloneDX 1.7 JSON.
The implementation follows
[ADR 0005](decisions/0005-cyclonedx-post-build-sbom.md) and the machine contract
in `distribution/windows/sbom-contract-v0.1.json`.

## Builder-only dependency

Install the generator/validator dependency explicitly:

```powershell
python -m pip install -e ".[sbom-builder]"
```

This pins `cyclonedx-python-lib==11.11.0`. It is a build and verification tool,
not a dependency that the desktop application may download or add to the frozen
runtime. Both creation and verification fail if this exact builder version is
unavailable.

## Required source evidence

Creation requires all of the following:

- the complete sealed one-directory bundle containing canonical
  `freeze-evidence.json` and `freeze-evidence.sha256` (schema 0.3);
- canonical `freeze-dependency-metadata.json` and its sidecar (schema 0.1);
- an externally recorded SHA-256 for each JSON source document; and
- an existing real output directory outside the sealed bundle.

The generator first runs the full bundle verifier. It then checks both exact
document/sidecar pairs, their external hashes, the dependency-to-freeze hash,
schema, source commit, bundle inventory, target, runtime package names and
versions, and dependency package-set aggregate. A sidecar copied from the same
possibly compromised location is not an independent expected hash; record the
expected values at the artifact or review boundary.

## Create

```powershell
python tools/desktop_sbom.py create C:\path\to\DiffeoForge `
  C:\path\to\evidence\freeze-dependency-metadata.json `
  --expect-freeze-evidence-sha256 <64-lowercase-hex> `
  --expect-dependency-evidence-sha256 <64-lowercase-hex> `
  --output-directory C:\path\to\evidence
```

The command creates exactly:

- `freeze-sbom.cdx.json`; and
- `freeze-sbom.cdx.sha256`.

Neither file is overwritten. Existing or symbolic output files, a symbolic or
missing output directory, and an output directory inside the frozen bundle are
rejected. If either write or the mandatory post-write verification fails, files
created by that attempt are removed.

## Deterministic mapping

- format and validator: CycloneDX 1.7 JSON and the pinned official Python
  library's strict 1.7 schema validator;
- lifecycle: `post-build`;
- serial number: UUIDv5 in the URL namespace from the exact dependency-evidence
  SHA-256;
- timestamp: the exact freeze-evidence `created_at` value;
- root: DiffeoForge application version plus source commit, target, bundle
  inventory, source-evidence hashes, package-set hash, boundaries, and open
  gates as namespaced properties;
- packages: required `library` components, sorted by normalized PyPI Package
  URL;
- component hashes: omitted because a `METADATA` or license-file hash is not a
  hash of the complete distribution archive or frozen component payload;
- licenses: a present SPDX-valid `License-Expression` is emitted as an
  expression; legacy fields, classifiers, declared paths, observations, and
  exact license-file records remain `diffeoforge:evidence:*` properties with
  review status `unreviewed`;
- graph: no dependency edges are inferred from raw `Requires-Dist`; composition
  is explicitly `incomplete`; and
- bytes: UTF-8, sorted JSON keys, two-space indentation, and exactly one final
  line feed.

Identical source-evidence bytes and external hashes therefore produce identical
SBOM bytes.

## Verify downloaded evidence

The verifier can operate on the six downloaded evidence files without the
unsigned application bundle:

```powershell
python tools/desktop_sbom.py verify `
  C:\download\freeze-sbom.cdx.json `
  C:\download\freeze-evidence.json `
  C:\download\freeze-dependency-metadata.json `
  --expect-freeze-evidence-sha256 <64-lowercase-hex> `
  --expect-dependency-evidence-sha256 <64-lowercase-hex> `
  --expect-sbom-sha256 <optional-independent-64-lowercase-hex>
```

Verification checks the exact three sidecars, optional independent SBOM hash,
canonical JSON, strict CycloneDX 1.7 schema, SPDX expressions, all source
bindings, ordering, and a byte-for-byte reconstruction of the deterministic
mapping. It rejects a schema-valid SBOM whose sidecar was recomputed after
tampering.

The downloaded-evidence path can recompute the freeze manifest's internal
counts and inventory aggregate, but it cannot re-hash files from an absent
bundle. Only `python tools/desktop_bundle_evidence.py verify <bundle>` proves
that the manifest still matches a complete local bundle.

## Deliberate boundary

A schema-valid SBOM is still not a human-reviewed license inventory,
compatibility analysis, or redistribution approval. The current manual
clean-runner workflow still uploads four files, not six; it has not yet produced
or independently observed an SBOM artifact. Signing, installer/uninstaller,
Defender, clean-VM, no-network, crash, CPU numerical, and scientific release
evidence remain separate gates.
