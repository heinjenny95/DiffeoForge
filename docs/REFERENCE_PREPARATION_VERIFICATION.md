# Saved reference preparation verification

Status: **strict read-only artifact verification; no current-input or execution claim**

Save the plan JSON and optional deterministic HTML review, then verify them in a
later process or environment:

```powershell
diffeoforge reference-plan atlas.yaml --run-id pilot-001 `
  --report review/pilot-001.html > review/pilot-001.json

diffeoforge reference-plan-verify review/pilot-001.json `
  --report review/pilot-001.html `
  --output review/pilot-001-plan-verification.json
```

Without `--output`, the verifier writes one exact ASCII-safe JSON evidence
document directly to binary stdout and creates no file. With `--output`, it
writes those same deterministic bytes exclusively to a new file, rereads them,
and prints the complete-file SHA-256. The parent directory must already exist;
an existing file, link, missing parent, or linked parent is rejected without a
sidecar. It accepts the report only when its UTF-8 bytes exactly equal a fresh
deterministic rendering from the saved plan.

Independently record the complete verification-evidence hash before archiving
or sharing the file. That hash binds the exported evidence bytes, whereas
`--expect-fingerprint` binds the canonical saved plan values to an external
review record.

## External fingerprint binding

Self-consistency cannot show whether someone deliberately replaced both the
plan and its regenerated report. Record the HTML-visible canonical plan
fingerprint in an independent location such as a project log, release manifest,
methods supplement, or signed record. Bind it during verification:

```powershell
diffeoforge reference-plan-verify review/pilot-001.json `
  --report review/pilot-001.html `
  --expect-fingerprint 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

The fingerprint is SHA-256 over a sorted, compact, ASCII-safe JSON
representation of the plan values. JSON indentation and final-newline choices
do not affect it. The verifier normalizes an uppercase expected hexadecimal
value to lowercase but rejects every value that is not exactly 64 hexadecimal
digits.

## Strict saved-plan checks

The verifier requires:

- strict UTF-8 without a byte-order mark;
- exactly one JSON document with only trailing JSON whitespace;
- no duplicate object keys at any nesting level;
- no `NaN`, `Infinity`, or `-Infinity` constants;
- the supported `reference-preparation-plan-v0.1` schema;
- a computable canonical plan fingerprint;
- an exact expected-fingerprint match when supplied;
- exact deterministic HTML bytes when a report is supplied; and
- unchanged saved-plan and report bytes from first read through final evidence
  validation.

Evidence schema `reference-preparation-plan-verification-v0.1.json` records the
saved-file byte hashes, canonical and optional expected fingerprint, report hash
and regeneration result, the recorded run ID/destination/counts, completed
checks, DiffeoForge version, and the interpretation boundary.

The evidence serializer validates this schema again before writing sorted,
indented, ASCII-safe JSON with exactly one final newline. File output and
stdout therefore use the same shared byte contract and do not rely on shell
redirection or platform text encoding.

## Interpretation boundary

Verification concerns saved artifacts only. It does not reread the config or
mesh paths embedded in the plan, and it does not claim that those files still
exist or retain their recorded hashes. It does not prove that the recorded run
destination is still absent, that preparation or execution occurred, or that
parameters, convergence, registration, engine equivalence, or biological
interpretation are valid.

Use `reference-plan` again for a new current-state preview. A future explicit
preparation gate must compare its reviewed plan to the bytes it will actually
stage; this verifier does not grant preparation or execution permission.

To record explicit intent for one exact reviewed fingerprint, create and later
fresh-state verify a
[reference preparation-only approval request](REFERENCE_PREPARATION_APPROVAL.md).
That artifact still does not prepare a run or authorize engine execution.
