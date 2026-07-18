# Saved reference preparation status verification

Status: **strict saved-artifact verification; no current-state inspection**

Create one exact report without shell-dependent text redirection:

```powershell
diffeoforge reference-preparation-status review\pilot-001-approval.json `
  --current-config atlas.yaml `
  --expect-request-sha256 THE_INDEPENDENTLY_RECORDED_APPROVAL_SHA256 `
  --output review\pilot-001-preparation-status.json
```

`--output` creates one file exclusively in an existing real parent directory.
It never replaces an existing file or link. The command writes the same
deterministic UTF-8 bytes retained by the desktop exporter. `--json` still
emits those exact bytes to standard output, but `--output` avoids PowerShell
version-specific native-output re-encoding.

Independently record the complete file hash, for example:

```powershell
(Get-FileHash review\pilot-001-preparation-status.json -Algorithm SHA256).Hash
```

Then verify only the saved artifact:

```powershell
diffeoforge reference-preparation-status-verify `
  review\pilot-001-preparation-status.json `
  --expect-report-sha256 THE_INDEPENDENTLY_RECORDED_REPORT_SHA256
```

Exit code 0 emits versioned ASCII-safe verification evidence. Invalid hash,
strict JSON, schema, deterministic representation, or a file race fails closed
with exit code 2 and does not repair the artifact.

## Checks

The verifier:

1. reads the complete saved report bytes;
2. requires the independently supplied SHA-256 to match those bytes;
3. strict-loads exactly one UTF-8 JSON object with unique keys and finite
   constants;
4. validates `reference-preparation-reconciliation-v0.1.json`;
5. requires exact equality to DiffeoForge's sorted-key, two-space-indented,
   final-newline deterministic serialization;
6. requires the report to record `mutation_performed: false` and a stable
   repeated observation;
7. validates separate
   `reference-preparation-reconciliation-verification-v0.1.json` evidence; and
8. rereads the saved file and fails if any byte changed during verification.

The evidence records the saved report identity, report status, run ID,
approval hash, plan fingerprint, destination classification, optional manifest
hash, engine-execution observation, and private-stage count. It does not copy
the full nested report.

## Deliberately absent reads and claims

Verification reads no current YAML, mesh, approval, destination, private-stage,
process, container, or engine state. The recorded paths may no longer exist and
verification can still succeed because it concerns the saved artifact only.

The report and evidence contain provenance paths or identifiers and should be
reviewed before sharing. A successful result does not prove that the recorded
external state remains current. It grants no preparation, publication,
recovery, resume, cancellation, or execution authority and makes no claim
about parameters, numerical validity, convergence, registration, atlas
quality, or biological interpretation.
