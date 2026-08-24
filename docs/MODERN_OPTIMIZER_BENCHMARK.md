# Modern multi-cycle optimizer benchmark

## Purpose

`modern-optimizer-benchmark` measures the actual production block optimizer,
including Armijo line searches, for an explicitly bounded subject prefix and
cycle count. It complements `modern-benchmark`, which measures one declared
objective plus gradient. The protocol exists to make optimizer changes
observable and regression-testable; it is not a speed claim against
Deformetrica.

## Command

```powershell
diffeoforge modern-optimizer-benchmark modern-atlas.yaml `
  --subjects 5 --cycles 3 --repeats 3

diffeoforge modern-optimizer-benchmark-verify `
  modern-atlas.optimizer-benchmark
```

`--subjects` selects the first meshes in the already validated deterministic
path order. `--cycles` is a benchmark-only cap; the source YAML and its
configured `optimization.max_cycles` are preserved and both values are stored
in the report. `--warmups` optionally performs complete optimizer runs inside
each worker before the measured run. Its default is zero because a full warm-up
can itself be expensive. One-, two-, and three-block optimizer orders are all
valid, so the same benchmark can measure fixed-reference momenta-only
qualification runs without pretending that template or control-point updates
occurred. Blockwise reports preserve the configured `standard` or `recompute`
autograd strategy alongside both tile dimensions.

## Isolation and timing boundary

Every repeat uses a new multiprocessing `spawn` process. The worker loads the
same reviewed configuration, applies its thread count and random seed, and
builds the same deterministic initial template, control points, and zero
momenta as the Modern workflow.

Fixed-target attachment data are prepared once per fresh process. Their
preparation time is recorded separately. The measured optimizer interval then
reuses those caches and excludes:

- configuration and mesh loading;
- tensor and control-point initialization;
- target-cache preparation;
- optional warm-up runs;
- result-bundle, PCA, plot, and disk-publication work.

Process RSS is sampled every 5 ms during the measured optimizer interval. A
shorter memory peak can be missed, so the observation is explicitly called a
sampled process peak rather than a peak-RAM guarantee.

## Exact work counters

Each repeat records:

- accepted, stationary, and failed optimizer decisions;
- line-search objective evaluations;
- all objective and gradient evaluations;
- candidate gradients actually requested after passing the Armijo objective
  threshold;
- line-search candidates rejected without a backward pass;
- termination reason, completed cycles, and final objective components.

For a multi-block optimizer, the verifier checks
`objectives = decisions + line-search evaluations` and
`gradients = decisions + candidate gradients`. A one-block optimizer reuses
the accepted candidate gradient at the next cycle boundary, so its exact
identities are `objectives = 1 + line-search evaluations` and
`gradients = 1 + candidate gradients`. These counters therefore expose whether
a runtime change reflects less mathematical work rather than only a wall-clock
fluctuation, without rejecting the documented single-block reuse path.

When `subject_batch_size` is enabled, every requested gradient intentionally
recomputes one graph-free complete-cohort objective in bounded subject batches.
The verifier therefore additionally requires
`objectives = ordinary objectives + gradient evaluations`; it does not hide the
memory/runtime trade-off behind unchanged work counters.

## Repeatability evidence

Report v0.2 stores the complete decision history, not only its hash. Every
initial state and committed block decision retains its cycle, block, status,
objective components, subject residuals, gradient norm, accepted step, and
line-search count. The strict verifier reconstructs the frozen block order,
status totals, completed-cycle count, line-search total, final values, and
history SHA-256. A changed or omitted v0.2 record therefore fails closed.
Historical v0.1 reports remain verifiable under their hash-only contract.

The report also hashes the final template, control-point, and momenta tensors.
Fresh-process repeats are marked consistent only when these hashes and all
discrete counters match exactly and final objective components agree within the
declared `1e-12` absolute and relative tolerance.

The output directory contains:

- `optimizer-benchmark.json`: versioned authoritative evidence;
- `samples.csv`: exact flat per-repeat observations;
- `optimizer-benchmark.html`: escaped human review page regenerated from JSON.

Publication is atomic. `--force` replaces only a directory that first verifies
as a generated optimizer benchmark. The dedicated verify command rejects added
files, schema drift, inconsistent counters, CSV changes, or HTML changes.

New reports bind the separate Modern engine implementation revision in their
environment record. Reports created before that field existed remain strictly
verifiable, but cannot be mixed into or resumed as a newly frozen
implementation-bound scaling study.

## Scientific boundary

A limited prefix and cycle count do not establish convergence, robustness,
scientific validity, an end-to-end runtime, an ETA to convergence,
300-subject feasibility, or
superiority over Deformetrica. Scaling and backend comparisons require a
prospectively frozen design with independently verified runs. The immutable
[optimizer scaling design](MODERN_OPTIMIZER_BENCHMARK_DESIGN.md) now freezes the
subject-by-cycle factorial before measurement. Its resumable executor verifies
unchanged source identity, retains every raw condition report, and binds the
completed run with a strict manifest without performing an automatic analysis.
During optimizer-study execution, committed decisions may support a clearly
labelled observed-rate ETA to the configured decision cap. It is live-only,
low-confidence, and neither persisted as a fitted model nor interpreted as
scientific convergence.
