# Reference preparation-only approval

Status: **versioned immutable intent record; no preparation or engine execution**

The approval command closes the gap between reviewing an exact preparation
plan and recording which exact bytes were accepted. Approval creation itself
does not create a run directory. The generic `prepare` command ignores the
artifact; only the separate `reference-prepare-approved` command consumes it.

First save and review a plan and its offline HTML page:

```powershell
diffeoforge reference-plan atlas.yaml --run-id pilot-001 `
  --report review/pilot-001.html > review/pilot-001.json

diffeoforge reference-plan-verify review/pilot-001.json `
  --report review/pilot-001.html `
  --expect-fingerprint THE_64_DIGIT_SHA256_FROM_THE_REVIEW
```

Only after review, copy that canonical plan fingerprint into a new approval
request:

```powershell
diffeoforge reference-plan-approve atlas.yaml `
  --run-id pilot-001 `
  --approve-fingerprint THE_64_DIGIT_SHA256_FROM_THE_REVIEW `
  --output review/pilot-001-approval.json
```

The command freshly recomputes the complete plan from the current config and
meshes. It succeeds only when that fresh canonical fingerprint exactly matches
the supplied reviewed fingerprint. The JSON printed to stdout and written to
the exclusive output path embeds the complete approved plan. Existing output
files are never replaced.

## Exact scope

Schema `reference-preparation-approval-v0.1.json` fixes the approval to:

- scope `preparation_only`;
- status `approved_reference_preparation_not_prepared`;
- the complete schema-valid reference preparation plan;
- its canonical SHA-256 fingerprint;
- the statement that only creation of that plan's immutable staged run
  directory is approved; and
- `engine_execution_authorized: false`.

It records no person, timestamp, account, or signature. Therefore it is a
deterministic workflow artifact, not proof of identity, authorship, informed
consent, or a cryptographic signature. Store authorship and review decisions in
the project log or another independently controlled record.

The approval does not validate scientific parameters, mesh homology,
registration, convergence, numerical equivalence, or biological
interpretation. It never grants Docker, Deformetrica, or another engine
permission to run.

## Read-only verification

Check the saved request's internal integrity without consulting current inputs:

```powershell
diffeoforge reference-plan-approval-verify review/pilot-001-approval.json
```

For the stronger current-state check, supply the config again:

```powershell
diffeoforge reference-plan-approval-verify review/pilot-001-approval.json `
  --current-config atlas.yaml `
  --output review/pilot-001-approval-verification.json
```

The second form freshly reconstructs the plan using the embedded normalized run
ID. It fails when any plan-bound value differs, including configuration bytes,
mesh inventory or bytes, generated YAML/XML, backend contract, host-sensitive
serialization, command preview, or destination absence.

Both forms parse strict UTF-8 JSON, reject duplicate keys, non-finite constants,
trailing documents, schema violations, embedded-plan/fingerprint disagreement,
and request changes during verification. Without `--output`, the verifier
writes versioned `reference-preparation-approval-verification-v0.1` evidence
directly to binary stdout and creates no file. With `--output`, it writes the
same schema-revalidated, deterministic ASCII bytes exclusively to a new file,
rereads them, and prints their complete-file SHA-256. The parent must already
exist and be a real directory; existing targets, links, missing parents, and
linked parents fail closed without a sidecar.

Independently record the complete verification-evidence hash before archiving
or sharing it. Evidence export does not strengthen approval scope, prove
identity, or authorize preparation or execution.

## Atomic consumer boundary

The CLI now has a separate approval-aware mutating consumer. It additionally
requires an independently recorded hash of the complete request, freshly
recomputes the plan, exact-matches private staged bytes, publishes without
replacement, verifies the pristine prepared run, and stops before execution.
See [atomically prepare an approved reference plan](REFERENCE_APPROVED_PREPARATION.md).

The generic `diffeoforge prepare` command still does not consume this approval
artifact. The frozen desktop reference worker also remains nonmutating until a
separate parent-supervised worker slice is reviewed.
