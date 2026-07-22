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
can itself be expensive.

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

The verifier checks the optimizer identities
`objectives = decisions + line-search evaluations` and
`gradients = decisions + candidate gradients`. These counters therefore expose
whether a runtime change reflects less mathematical work rather than only a
wall-clock fluctuation.

## Repeatability evidence

The report hashes the complete decision history and the final template,
control-point, and momenta tensors. Fresh-process repeats are marked consistent
only when these hashes and all discrete counters match exactly and final
objective components agree within the declared `1e-12` absolute and relative
tolerance.

The output directory contains:

- `optimizer-benchmark.json`: versioned authoritative evidence;
- `samples.csv`: exact flat per-repeat observations;
- `optimizer-benchmark.html`: escaped human review page regenerated from JSON.

Publication is atomic. `--force` replaces only a directory that first verifies
as a generated optimizer benchmark. The dedicated verify command rejects added
files, schema drift, inconsistent counters, CSV changes, or HTML changes.

## Scientific boundary

A limited prefix and cycle count do not establish convergence, robustness,
scientific validity, an end-to-end runtime, an ETA, 300-subject feasibility, or
superiority over Deformetrica. Scaling and backend comparisons require a
prospectively frozen design with independently verified runs. The immutable
[optimizer scaling design](MODERN_OPTIMIZER_BENCHMARK_DESIGN.md) now freezes the
subject-by-cycle factorial before measurement; its future executor remains a
separate gate.
