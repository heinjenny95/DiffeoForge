# Atomically prepare an approved reference plan

Status: **exact approval-aware staging; verified stop before engine execution**

`reference-prepare-approved` is the only current command that consumes a
preparation-only approval request. It atomically creates exactly the immutable
run directory embedded in that request and returns with a pristine `prepared`
lifecycle. It never starts Docker, Deformetrica, or another engine process.

## Complete review-to-preparation workflow

Create and review the exact plan, then record preparation-only approval as
described in
[reference preparation-only approval](REFERENCE_PREPARATION_APPROVAL.md).
Strictly verify the request and save its evidence:

```powershell
diffeoforge reference-plan-approval-verify review/pilot-001-approval.json `
  --current-config atlas.yaml |
  Out-File -Encoding ascii review/pilot-001-approval-verification.json
```

Copy `request.sha256` from that verification evidence into the mutating command:

```powershell
diffeoforge reference-prepare-approved review/pilot-001-approval.json `
  --current-config atlas.yaml `
  --expect-request-sha256 THE_INDEPENDENTLY_RECORDED_REQUEST_SHA256 |
  Out-File -Encoding ascii review/pilot-001-preparation-evidence.json
```

The external request hash is mandatory. The embedded plan fingerprint alone
cannot detect deliberate replacement of the complete request with another
self-consistent request. Record both hashes in the project log or another
independently controlled provenance record.

## Fail-closed sequence

The consumer performs these gates in order:

1. strict-load and schema/fingerprint validate the saved approval request;
2. require its complete bytes to match the independently recorded SHA-256;
3. freshly recompute the complete plan from the current config and meshes;
4. require value equality and canonical-fingerprint equality with the embedded
   approved plan;
5. privately stage the run under a hidden temporary directory;
6. require run ID, paths, config hash, backend contract, effective config,
   input metadata, every protected path/byte count/SHA-256, generated YAML/XML
   bytes, totals, and command preview to match the approved plan;
7. reread the approval request immediately before publication;
8. validate the versioned stopped-before-execution evidence;
9. atomically publish without replacing a destination that appeared during
   staging; and
10. reverify the immutable manifest, protected artifacts, sole `prepared`
    lifecycle event, empty output, and absence of execution artifacts.

Private staging is removed on failure. The final run destination is absent
unless every prepublication gate passes. An output-root directory may remain
empty after a failed private stage. If another process creates the final
destination during staging, DiffeoForge preserves that directory and its
contents and fails.

After a suspected hard crash, use the approval-bound
[read-only preparation status](REFERENCE_PREPARATION_RECONCILIATION.md). It can
distinguish an absent destination, a verified published prepared run, a
complete but still unpublished private stage, and incomplete, mismatched, or
unsafe state. It never performs recovery or cleanup.

Linux uses `renameat2(RENAME_NOREPLACE)` and Windows uses non-replacing
directory rename semantics for atomic publication. Other platforms retain an
explicit pre-rename absence check but have not yet received the same
platform-specific no-replace validation.

## Versioned evidence

Schema `reference-approved-preparation-v0.1.json` records:

- approval-request path, byte count, observed SHA-256, and externally expected
  SHA-256;
- approved canonical plan fingerprint, normalized run ID, destination, subject
  count, protected-file count, and protected bytes;
- prepared run and manifest paths, manifest byte count and SHA-256;
- the verified `prepared` lifecycle, pristine output, and
  `engine_execution_started: false`;
- the ten completed preparation gates; and
- the narrow scientific interpretation boundary.

The JSON is printed as the sole ASCII-safe stdout document. No evidence sidecar
is silently added to the approved run because that would change the exact
staged contents that were reviewed. The immutable run's own manifest, checksum,
protected inventory, and event log remain the durable primary evidence.

## Boundary

This command prepares files; it does not estimate an atlas. It does not prove
the identity or authority of an approver and does not validate parameters,
mesh homology, registration, convergence, numerical equivalence, or biological
interpretation. Engine execution remains a separate `diffeoforge execute`
action.

The frozen nonnumerical reference-worker harness remains intentionally restricted to
`stopped_before_prepare`. A separate
[approval-bound preparation worker](REFERENCE_PREPARATION_WORKER.md) now
consumes this service over a strict pipe and emits a reconciled
`prepared_not_executed` lifecycle. It is parent-contained in source and frozen
evidence paths but is not wired into the GUI, and it still cannot authorize or
start engine execution.
