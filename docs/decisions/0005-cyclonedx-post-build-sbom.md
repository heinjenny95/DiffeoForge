# ADR 0005: Use deterministic CycloneDX 1.7 JSON for the first post-build SBOM

- Status: Accepted; generator implemented and clean-runner observation complete
- Date: 2026-07-18
- Issue: [#151](https://github.com/heinjenny95/DiffeoForge/issues/151)

## Context

The Windows freeze now produces an exact bundle inventory and a separately
freeze-hash-bound inventory of installed Python distribution metadata and
license-related files. Neither document is a standard SBOM. A conversion must
not turn a `METADATA` hash into a hash of a package archive or frozen component,
promote legacy license text into a reviewed SPDX identity, or present raw
`Requires-Dist` declarations as a complete runtime dependency graph.

The current standards considered were CycloneDX 1.7 and SPDX 3.0.1. Both can
represent software packages and package URLs. CycloneDX 1.7 directly represents
post-build lifecycle, tools, components, dependency relationships, evidence,
and explicit composition completeness in one JSON BOM. This aligns closely
with the existing freeze-evidence boundary and provides an official Python
library with schema-based JSON validation for version 1.7.

## Decision

The first Windows post-build SBOM will be CycloneDX 1.7 JSON, generated and
schema-validated with builder-only `cyclonedx-python-lib==11.11.0`. The exact
machine contract is `distribution/windows/sbom-contract-v0.1.json`. The tool is
not a bundled runtime dependency and its pin is not permission to redistribute
any application component.

Generation will require externally recorded SHA-256 values for both the exact
freeze manifest and dependency-metadata evidence. The BOM serial number will
be deterministic UUIDv5 in the URL namespace from the dependency-evidence
SHA-256, the timestamp will reuse the exact freeze-evidence creation time, BOM
version will be one, components will be ordered by purl, and final JSON will be
canonical UTF-8 with sorted keys, two-space indentation, and one trailing LF.
Existing or symbolic outputs and output inside the sealed bundle will be
refused.

DiffeoForge is the root `application`. Each package in the dependency evidence
becomes a required `library` component with a normalized PyPI package URL.
`METADATA` and license-file hashes remain evidence properties; they are not
CycloneDX component hashes because they do not hash the complete distribution
archive or frozen payload.

Only a present `License-Expression` may enter CycloneDX's expression field, and
only if the official schema accepts it. Legacy `License`, classifiers, and
license-file hashes remain explicitly unreviewed properties. They do not imply
compatibility or redistribution approval.

The first generator will omit dependency edges. `Requires-Dist` can contain
environment markers, extras, build/test requirements, and dependencies absent
from the frozen runtime set; the current evidence does not prove a resolved
runtime graph. CycloneDX composition will therefore be `incomplete`. A future
graph slice must record and bind the complete marker-evaluation environment and
prove edge resolution before changing that claim.

The output pair is `freeze-sbom.cdx.json` and
`freeze-sbom.cdx.sha256`, written outside the bundle. Implementation and upload
integration were followed by a separate clean-runner observation before the
six-file evidence boundary was accepted. Run
[29638832620](https://github.com/heinjenny95/DiffeoForge/actions/runs/29638832620)
is that first accepted observation; the exact artifact audit is documented in
the Windows freeze evidence. No SBOM file is uploaded merely because this ADR
exists.

## Consequences

- consumers receive a current, widely supported JSON SBOM format;
- identical source evidence produces identical SBOM bytes;
- the SBOM remains traceable to source commit, bundle inventory, freeze
  manifest, dependency evidence, and package-set hash;
- package metadata and license evidence remain visible without acquiring a
  stronger meaning than their source supports;
- composition incompleteness is machine-readable rather than hidden;
- an official schema validator becomes a pinned builder dependency;
- license inventory review, compatibility analysis, and redistribution
  approval remain named human release gates;
- installer, signing, antivirus, clean-VM, network, numerical, and scientific
  gates remain unchanged.

## Rejected for the first SBOM

- SPDX 3.0.1 as the primary first format: valid and retained as a future export
  option, but less directly aligned with the current post-build evidence and
  chosen Python validation path;
- CycloneDX 1.6: superseded by current version 1.7;
- random serial numbers or current-clock timestamps that make identical
  evidence produce different bytes;
- package component hashes derived from `METADATA` or license files;
- inferred SPDX identifiers from legacy free text or classifiers;
- a complete dependency graph inferred from raw `Requires-Dist` strings;
- treating a schema-valid SBOM as license or redistribution approval.

## Primary standards references

- [CycloneDX specification overview](https://cyclonedx.org/specification/overview/)
- [CycloneDX 1.7 JSON reference](https://cyclonedx.org/docs/1.7/json/)
- [CycloneDX Python Library output and supported schemas](https://cyclonedx-python-library.readthedocs.io/en/latest/outputting.html)
- [SPDX 3.0.1 specification](https://spdx.github.io/spdx-spec/)
