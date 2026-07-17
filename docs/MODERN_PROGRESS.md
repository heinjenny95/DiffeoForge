# Versioned modern workflow progress

Status: **implemented observer and desktop transport contract; not an ETA or
checkpoint protocol**

Tracked prospectively by
[engineering issue #36](https://github.com/heinjenny95/DiffeoForge/issues/36).

## User-visible behavior

`diffeoforge modern-run modern-atlas.yaml` now prints progress while the shared
application service executes. A stage line names completed work:

```text
Progress [3/7 stages] quality completed: Input mesh quality gates passed
```

During optimization, decision lines add the configured block-decision bound:

```text
Progress [4/7 stages; optimizer 1/3 decisions] cycle 1/1 momenta accepted; objective=...; line-search=1
```

The denominator is a count of configured parameter-block decisions, not a
time estimate. Objective evaluations have very different costs from file
copying, PCA, verification, or report generation. DiffeoForge therefore does
not label these counts as percent complete and does not calculate an ETA.

## Application-service contract

`run_modern_workflow(..., progress_callback=observer)` accepts an optional
synchronous callback. Each callback value is an immutable
`ModernProgressEvent` and serializes with `as_dict()` against the bundled
strict schema `modern-progress-v0.1.json`.

The seven ordered stages are:

1. inputs copied and parsed;
2. optional preprocessing completed;
3. input mesh-quality gates passed;
4. atlas tensors initialized;
5. optimization completed;
6. atlas/PCA bundle created and verified; and
7. outer workflow evidence verified.

A preceding `workflow/started` event has zero completed stages. An
`optimization/started` event precedes optimizer decisions. Successful return
from `run_modern_workflow` remains the authoritative signal that atomic
publication into the requested final directory succeeded.

The callback runs in the compute thread. If it raises before publication, the
run fails and the private temporary directory is removed. This makes observer
failure explicit and preserves the existing no-partial-publication contract.

## Optimizer observer semantics

The dense `optimize_atlas(..., progress_callback=observer)` observer receives
the exact immutable `AtlasOptimizationRecord` objects appended to final
history. It emits:

- the fully evaluated initial state;
- one accepted or stationary record per committed block decision; or
- one failed record when line search terminates the optimizer.

Rejected or non-finite line-search candidates are internal evaluations, not
accepted states, and are never emitted as separate progress decisions. Tests
require the observed record tuple to equal `result.history` exactly and prove
that observed and unobserved runs have identical parameters and history.

## Desktop boundary and current limits

The CLI and the source-level desktop child worker consume the same event
dictionary instead of inventing separate scientific logic. The worker wraps it
unchanged in strict JSON Lines events and accepts one cooperative cancellation
command. Safe-point cancellation removes private temporary work and publishes
no destination. See [Versioned desktop worker protocol](DESKTOP_WORKER.md).

The worker transport does not add checkpoints, resume, persisted partial runs,
runtime calibration, peak-memory measurement, or ETA prediction. GUI execution
controls and crash reconciliation are not yet connected.

## Frozen benchmark-study progress

The resumable benchmark-study service has a separate strict v0.1 observer
because its unit of committed work is a verified condition report, not an atlas
workflow stage or optimizer decision. It emits immutable start/resume,
condition, reconciliation, interruption, completion, and already-complete
events with exact completed/total condition counts and frozen condition
identity.

`diffeoforge modern-benchmark-study` prints these events. Counts are never
converted to elapsed-time percentages or ETA: different subject prefixes and
autograd strategies can have materially different costs. A callback that does
not raise is observational only; tests require byte-identical published study
evidence with and without it. See the
[prospective benchmark-study protocol](MODERN_BENCHMARK_STUDY.md).
