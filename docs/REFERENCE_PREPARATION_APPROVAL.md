# Reference preparation-only approval

Status: **versioned immutable intent record; no preparation or engine execution**

The approval command closes the gap between reviewing an exact preparation
plan and recording which exact bytes were accepted. It does not create a run
directory and is not consumed by `prepare` yet.

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
  --current-config atlas.yaml
```

The second form freshly reconstructs the plan using the embedded normalized run
ID. It fails when any plan-bound value differs, including configuration bytes,
mesh inventory or bytes, generated YAML/XML, backend contract, host-sensitive
serialization, command preview, or destination absence.

Both forms parse strict UTF-8 JSON, reject duplicate keys, non-finite constants,
trailing documents, schema violations, embedded-plan/fingerprint disagreement,
and request changes during verification. The verifier prints versioned
`reference-preparation-approval-verification-v0.1` evidence and writes nothing.

## Future atomic consumer boundary

This release intentionally stops before mutation. A future preparation worker
must accept the approval request explicitly, freshly recompute the entire plan
immediately before staging, require exact canonical fingerprint equality and an
absent destination, then atomically create only that immutable staged run. It
must stop before engine execution. The existing `diffeoforge prepare` command
does not yet consume or enforce this approval artifact.
