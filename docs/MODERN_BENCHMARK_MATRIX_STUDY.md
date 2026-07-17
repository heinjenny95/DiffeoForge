# Resumable multi-tile benchmark matrix study

The matrix study service executes exactly one prospectively frozen
matrix-design v0.1 artifact. It preserves every objective/gradient observation
as a separate raw benchmark v0.4 report. It does not aggregate, compare, rank,
or recommend conditions.

## Execute or resume

```powershell
diffeoforge modern-benchmark-matrix-study `
  modern-atlas.benchmark-matrix `
  modern-atlas.yaml
```

The service first verifies the immutable design, re-collects the same design
from the supplied config and complete current input inventory, and requires
exact equality. It then copies the design directory and exact config bytes into
`modern-atlas.benchmark-matrix.run`.

For each condition, the runner passes the frozen subject prefix, repeats,
warm-ups, autograd strategy, query tile size, and source tile size to
`modern-benchmark`. Both explicit tile overrides are mandatory, so every raw
report is contract v0.4. Immediate verification requires its source-declared
plan, effective plan, strategy, selected inputs, protocol, operation model,
JSON, CSV, and regenerated HTML to agree before state advances.

## Interruption and recovery

Atomic state records a contiguous prefix of condition IDs. The condition
directory may contain only that prefix or one or more subsequently verified
reports written before an interruption prevented state advancement. On resume,
the runner verifies and reconciles those reports without overwriting them.

The inverse is unsafe: if state claims a completed condition whose report is
missing, status and execution both stop. Reports outside frozen order, unknown
directories, altered config/design bytes, incompatible effective plans, and an
active process-identity lock also stop execution. A stale same-host lock is
recoverable; a live or foreign-host lock is not silently stolen.

## Exact-count progress and read-only status

Progress v0.2 is synchronous and immutable. Condition events include sequence,
condition ID, cell ID, subject count, effective query/source tile plan, and
strategy. Counts are exact completed/total conditions. No percentage, elapsed
fraction, ETA, forecast, or comparative result exists in the event schema.

Read status without reconciling or writing:

```powershell
diffeoforge modern-benchmark-matrix-study-status `
  modern-atlas.benchmark-matrix.run
```

`--json` returns the strict state/report counts, reconciliation flag, next
frozen condition and effective plan, manifest state, and lock observation.

## Completion evidence

After every condition is separately verified, study-run manifest v0.2 records:

- the copied matrix-design JSON and source-config hashes;
- each sequence, condition ID, cell ID, subject prefix, effective plan, and
  strategy; and
- SHA-256 values for each raw `benchmark.json`, `samples.csv`, and
  `benchmark.html`.

The event log must begin with creation, end with completion, use contiguous
sequence numbers, and list completed conditions in frozen order. Verify a
completed or copied run with:

```powershell
diffeoforge modern-benchmark-matrix-study-verify `
  modern-atlas.benchmark-matrix.run
```

The verifier regenerates the manifest while preserving only its completion
timestamp and requires the sidecar, state, events, copied inputs, exact report
prefix, and all raw artifacts to agree.

## Compatibility and scientific boundary

The single-tile `modern-benchmark-study` service, state, progress v0.1, manifest
v0.1, and raw v0.3 reports are unchanged. Matrix commands accept only the
matrix-design family and publish v0.2 run evidence; there is no silent version
fallback.

Completion does not show that one tile or strategy is faster, uses less peak
memory, is a safe preset, or makes a 300-subject atlas feasible. Sampled RSS is
not guaranteed peak memory, and objective/gradient timing is not full-workflow
runtime. Representative design freezing and the prospective analysis plan
remain later gates in
[ADR 0004](decisions/0004-prospective-multi-tile-matrix.md).
