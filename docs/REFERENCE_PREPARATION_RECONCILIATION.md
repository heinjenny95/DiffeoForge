# Approval-bound reference preparation status

Status: **strictly read-only reconciliation evidence; no recovery action**

`reference-preparation-status` explains the exact on-disk preparation state for
one externally hash-bound approval. It is safe to run before preparation, after
a successful `prepared_not_executed` result, or after a suspected controller,
worker, host, or power failure:

```powershell
diffeoforge reference-preparation-status review\pilot-001-approval.json `
  --current-config atlas.yaml `
  --expect-request-sha256 THE_INDEPENDENTLY_RECORDED_REQUEST_SHA256 `
  --output review\pilot-001-preparation-status.json
```

Omit `--json` for a short human-readable summary. Exit code 0 means either
`clear_to_prepare` or `published_prepared_not_executed_verified`. Exit code 1
means `attention_required`; it is not a command failure and performs no repair.
Invalid authorization, stale inputs, changing state, or malformed evidence
fails closed with exit code 2.

## Authorization and current-state binding

The report first strict-loads the complete approval request, requires its bytes
to match the separately supplied SHA-256, validates the embedded plan and
approval fingerprint, and freshly reconstructs the plan from the current
config and meshes. Reconciliation may reconstruct that prospective plan when
the immutable destination already exists; ordinary `reference-plan` retains
its refusal to plan over an existing destination.

The approval, config, current plan, destination observation, and private-stage
observation are checked again before the report is returned. If the exact
state differs between the two observations, no report is emitted.

## Exact inspection surface

Only these paths are considered:

- the destination embedded in the approved plan; and
- sibling names matching exactly
  `.diffeoforge-preparing-RUN_ID-` plus 32 lowercase hexadecimal characters.

Near matches and unrelated directories are ignored. Top-level links are never
followed. Each real candidate is walked without following links and must have
the exact approved prepared-run surface: planned directories, every protected
file, `events.jsonl`, `manifest.json`, and `manifest.sha256`, with no extra or
missing path. Its manifest, checksum, protected hashes, plan-bound metadata,
sole `prepared` lifecycle, empty output, and absence of execution artifacts are
then reverified.

Destination classifications are:

- `absent`;
- `verified_prepared_not_executed`;
- `unsafe_link` or `unsafe_content_link`;
- `not_directory`; or
- `incomplete_or_mismatched`.

Private-stage classifications are:

- `verified_complete_unpublished`;
- `unsafe_link` or `unsafe_content_link`;
- `not_directory`; or
- `incomplete_or_mismatched`.

A complete private stage remains private and is never presented as a published
result. The versioned `reference-preparation-reconciliation-v0.1.json` report
records `mutation_performed: false`, stable repeated observation, the external
approval hash, approved/current plan fingerprints, exact paths and statuses,
manifest hashes only for verified candidates, and
`engine_execution_started: false` only where that claim was actually verified.

The shared library also exposes a deterministic UTF-8 serialization with
sorted keys, two-space indentation, and one final newline. Desktop step 2
retains those exact immutable bytes and their SHA-256, then can write them only
to one explicitly selected new JSON file. That export never overwrites an
existing path and must be treated as private provenance because the report
contains absolute paths and file names.

The `--output` path is created exclusively in an existing real parent
directory and is never replaced. It avoids shell-dependent re-encoding of
native standard output. `--json` emits the same exact deterministic UTF-8 bytes
when a caller deliberately manages binary standard output. A saved report can
later be checked against an independently recorded complete-file SHA-256
without reading current external state; see
[saved status verification](REFERENCE_PREPARATION_RECONCILIATION_VERIFICATION.md).

## Boundary

This command never deletes, renames, publishes, resumes, prepares, executes,
repairs, or rewrites anything. It does not acquire a process lease and therefore
does not prove liveness. It does not choose whether a private stage should be
published, discarded, or retained. Those actions require a future explicit,
user-approved policy and separate mutation evidence. It also makes no claim
about crash recovery, engine containment, numerical validity, registration
quality, convergence, or biological interpretation. It is not wired into the
GUI as an execution or recovery authority; the desktop integration is limited
to the same read-only status and the explicit provenance-file export.
