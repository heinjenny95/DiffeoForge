# Engine 1.5 CUDA feasibility path

Status: **implemented and passing synthetic, five-subject, 16-subject, and
54-of-67-subject full-resolution Weevil gates; not a production default**

## Scope

Engine 1.5 adds an explicit CUDA/float64 execution device to the Modern Engine
without changing the generated CPU default or the qualified Engine 1.4 CPU
semantics. The path is intended to answer whether the existing exact Modern
objective can use the development RTX 4080 effectively before any GPU-specific
mathematical approximation or kernel rewrite is considered.

The official development environment is isolated at
`C:\Users\js7541\Documents\DiffeoForge-Runtimes\cuda-pytorch-2.11-cu128` and
currently contains PyTorch 2.11.0 with CUDA 12.8. The ordinary project virtual
environment remains CPU-only.

## Fail-closed contract

- `runtime.device` is exactly `cpu` or `cuda` and is bound in configurations,
  workflow manifests, bundles, workloads, benchmark designs, and reports.
- CUDA unavailability raises an error before a private run starts. There is no
  implicit CPU fallback.
- CUDA currently requires `subject_batch_workers: 1`; CPU thread-pool batching
  is not composed with GPU execution before a separate design proves it safe.
- Float64 remains mandatory. TF32 is disabled and PyTorch deterministic
  algorithms are requested.
- Benchmark timers synchronize CUDA before and after every measured interval.
- CUDA reports preserve allocator allocated/reserved baselines and peaks in
  addition to sampled host-process RSS.
- Live CUDA checkpoint and result tensors are copied to canonical CPU form
  before immutable serialization. Resume restores the state to the bound
  device.

## Evidence completed on 2026-08-24

An actual five-subject synthetic run completed all three optimizer decisions,
wrote and verified checkpoint v0.3, published a complete atlas/PCA bundle, and
passed strict verification through the ordinary CPU installation. Both the
workflow and nested bundle bind Engine `1.5` and device `cuda`.

Two fresh CUDA optimizer repeats were exactly repeat-consistent in decision
history and final tensor hashes. Their median optimizer time was 0.846 seconds,
with 30,402,048 bytes peak allocated and 35,651,584 bytes peak reserved CUDA
memory. A matched CPU control was faster on this tiny workload (0.274 seconds),
as expected when GPU launch overhead dominates. CPU and CUDA final objectives
differed by only `1.78e-13`; this is numerical agreement, not bitwise
cross-device identity.

Evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge CUDA Smoke Engine15`
- `C:\Users\js7541\Desktop\DiffeoForge CUDA Optimizer Benchmark Engine15`
- `C:\Users\js7541\Desktop\DiffeoForge CPU Optimizer Benchmark Engine15`

## Real-mesh tile screen

The initial frozen real-data design used blockwise recompute tiles of 64 rows.
That CPU-safe profile caused excessive tiny CUDA kernel launches and produced
no completed benchmark repeat after more than twelve minutes; the unpublished
benchmark was cancelled and left no output or private state. The immutable
no-results design remains at:

`C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.2-5-subject-engine15-cuda-screen`

One-subject full-resolution objective+gradient screens then measured:

| Recompute tile | Median wall time | Peak CUDA allocated |
|---:|---:|---:|
| 512 | 3.652 s | 41.52 MiB |
| 1024 | 1.482 s | 72.53 MiB |
| 2048 | 1.114 s | 192.70 MiB |
| 4096 | 1.071 s | 561.60 MiB |

Tile 2048 was selected before the optimizer gate because 4096 saved only 3.8%
while using 2.9 times as much allocated CUDA memory.

## Passing paired optimizer screen

The final screen uses the actual file-bound Deformetrica control points, five
full-resolution Weevil subjects, one L-BFGS cycle, subject batches of four, and
identical 2048-row blockwise recompute execution on CPU and CUDA. Both arms
used two fresh processes and were exactly repeat-consistent within device.

| Device | Median optimizer time | Result |
|---|---:|---|
| Ryzen 9 7950X CPU, four threads | 170.945 s | repeat-consistent |
| RTX 4080 CUDA/float64 | 16.801 s | repeat-consistent |

CUDA was 10.175 times faster (90.17% lower wall time). Final CPU/CUDA
objective and attachment differences were `8.53e-14`; regularity differed by
`1.11e-16`. CUDA used at most 241.16 MiB allocated and 460 MiB reserved memory.

Verified reports:

- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.3-5-subject-engine15-cuda-tile2048-file-controls-optimizer-benchmark`
- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.3-5-subject-engine15-cpu-tile2048-file-controls-optimizer-benchmark`

## Passing fixed-reference workflow gate

The frozen three-cycle CUDA qualification completed and verified all workflow,
checkpoint, atlas, reconstruction, and PCA artifacts. Its first assessment was
correctly `inconclusive_not_converged`, so a hash-bound exact-state successor
continued for up to 100 additional cycles. It converged after 81 successor
cycles, corresponding to the same total cycle 84 and final objective as the
historical converged CPU qualification.

The independent Deformetrica-reference assessment passed every predeclared
gate:

- Modern workflow verification: pass;
- Modern optimizer convergence: pass (`relative_objective_tolerance`);
- subject pass fraction: `1.0` (gate at least `0.8`);
- pooled Modern/reference external-residual ratio: `0.693624` (gate at most
  `1.2`); and
- cross-engine reconstruction p95/template diagonal: `0.0189684` (gate at
  most `0.05`).

The CUDA final objective differs from the earlier converged CPU qualification
by `1.38e-11`. The verified assessment is:

`C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.4-5-subject-engine15-cuda-continuation-100-cycles-assessment`

This five-subject gate established:

1. strict workflow, checkpoint, and bundle verification;
2. finite optimizer history with no failed block;
3. fresh-process CUDA repeat consistency;
4. CPU/CUDA objective-component agreement within predeclared `1e-10` absolute
   and relative tolerance for a matched mathematical protocol;
5. measured CUDA memory comfortably below the 16 GB device capacity; and
6. a material real-mesh wall-time benefit.

It authorized the separately frozen 16-subject CUDA gate described below.

## Passing 16-subject scaling gate

The prospective 16-subject screen used the same fixed reference, full-resolution
Weevil meshes, L-BFGS protocol, four-subject batching, and 2048-row blockwise
recompute execution. Two fresh one-cycle CUDA processes were exactly
repeat-consistent. Their median optimizer time was 54.203 seconds; peak CUDA
memory was 269,941,760 bytes allocated and 480,247,808 bytes reserved. This
left substantial headroom on the 16 GB RTX 4080 before the full run was
authorized.

The frozen three-cycle run completed and verified, then correctly assessed as
`inconclusive_not_converged`. Its hash-bound successor continued from the exact
CUDA checkpoint and converged after 80 successor cycles, corresponding to total
cycle 83. The CUDA final objective was `-21.78662026232653`; the historical CPU
qualification stopped at the same total cycle with objective
`-21.786620266871697`, an absolute difference of about `4.55e-9`.

The independent fixed-reference assessment passed every predeclared gate:

- Modern workflow verification: pass;
- Modern optimizer convergence: pass (`relative_objective_tolerance`);
- subject pass fraction: `1.0` (gate at least `0.8`);
- pooled Modern/reference external-residual ratio: `0.758305` (gate at most
  `1.2`); and
- cross-engine reconstruction p95/template diagonal: `0.0177346` (gate at
  most `0.05`).

All 16 individual subjects passed their external-residual gate, including the
morphologically unusual *Euparius* specimen. Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.5-16-subject-engine15-cuda-tile2048-optimizer-benchmark`
- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.6-16-subject-engine15-cuda-continuation-100-cycles-modern-run`
- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.6-16-subject-engine15-cuda-continuation-100-cycles-assessment`

This gate establishes correct CUDA checkpoint continuation and reference
non-inferiority at 16 full-resolution subjects. It authorizes a separately
frozen 67-subject resource and repeatability screen. It does not establish
biological validity or production readiness for 67, 236, or 300 subjects.

## Passing 54-of-67-subject scaling gate

Prospective screening found that 54 of the 67 protected reference subjects
passed the declared Modern input-quality gates. Twelve excluded meshes had
non-manifold edges, one had isolated vertices, and three of the non-manifold
meshes also had multiple face-connected components. The gates were not relaxed:
the excluded filenames and exact source-quality evidence remain frozen in the
qualification design.

The 54-subject one-cycle CUDA screen used two fresh processes. It was exactly
repeat-consistent in optimizer history and final tensor hashes, with median
optimizer time 185.434 seconds. Peak CUDA memory was 330,161,664 bytes allocated
and 541,065,216 bytes reserved, leaving substantial RTX 4080 headroom.

The three-cycle workflow passed strict verification and correctly assessed as
`inconclusive_not_converged`. Its hash-bound exact-state successor reproduced
the parent objective and converged after 40 successor cycles, corresponding to
total cycle 43. The final objective was `-74.40282977836408`; termination was
by `relative_objective_tolerance`.

The independent fixed-reference assessment passed every predeclared gate:

- Modern workflow verification: pass;
- Modern optimizer convergence: pass;
- subject pass fraction: `1.0` (gate at least `0.8`);
- pooled Modern/reference external-residual ratio: `0.844014` (gate at most
  `1.2`); and
- cross-engine reconstruction p95/template diagonal: `0.0145351` (gate at
  most `0.05`).

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.7-54-of-67-subject-engine15-cuda-tile2048-optimizer-benchmark`
- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.8-54-of-67-subject-engine15-cuda-continuation-100-cycles-modern-run`
- `C:\Users\js7541\Desktop\DiffeoForge Weevil Tests 2026-08-17\modern-reference-qualification-v1.8-54-of-67-subject-engine15-cuda-continuation-100-cycles-assessment`

This gate establishes verified CUDA execution, continuation, convergence, and
reference non-inferiority for every quality-eligible subject in the protected
67-subject cohort. It does not validate the 13 excluded topologies, biological
interpretation, or production readiness for the separate 236- or 300-subject
cohorts.

## Passing 236-subject 5k Trochanter qualification gate

The prospective fixed-reference qualification bound all 236 GPA-aligned,
approximately 5k-face Trochanter subjects, the selected Deformetrica reference
template and reconstructions, and Engine `1.5` CUDA execution before observing
Modern results. The frozen three-cycle workflow passed strict verification and
correctly assessed as `inconclusive_not_converged`.

Its separately frozen hash-bound successor reproduced the parent final
objective exactly as its initial objective (`-10850.491093571543`) and retained
Engine `1.5` on both sides of the continuation. It converged after 39 successor
cycles, corresponding to 42 total cycles, with termination by
`relative_objective_tolerance`. All 39 successor decisions were accepted, the
objective trajectory was non-decreasing, and no optimizer decision failed. The
final objective was `-341.43032459892913`, comprising attachment
`-196.48908506444724` and regularity `-144.94123953448195`.

The independently recomputed fixed-reference assessment passed every
predeclared engineering gate:

- Modern workflow verification: pass;
- Modern optimizer convergence: pass (required true);
- subject pass fraction: `1.0`, or 236/236 (gate at least `0.8`);
- pooled Modern/reference external-residual ratio: `0.769669` (gate at most
  `1.2`);
- cross-engine reconstruction p95/template diagonal: `0.0260470` (gate at
  most `0.05`); and
- every individual subject passed the external-residual ratio gate of at most
  `1.25`; the largest observed subject ratio was `0.964530`.

The pooled Modern external-residual p95 was `0.0437297`, compared with
`0.0568163` for the bound Deformetrica reference. These are external
surface-distance engineering results under the frozen protocol; they do not
establish biological validity or mathematical atlas equivalence.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-cuda-fixed-reference-qualification-v0.1-236-subject-modern-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-cuda-fixed-reference-qualification-v0.1-236-subject-assessment`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-cuda-fixed-reference-qualification-v0.2-236-subject-continuation-100-cycles`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-cuda-fixed-reference-qualification-v0.2-236-subject-continuation-100-cycles-modern-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-cuda-fixed-reference-qualification-v0.2-236-subject-continuation-100-cycles-assessment`

This gate establishes verified CUDA execution, exact-state continuation,
convergence, and Deformetrica-reference engineering non-inferiority at the full
236-subject 5k Trochanter scale. It does not yet establish production readiness
for an independent 300-subject cohort, biological interpretation, or a general
safe preset across anatomies and mesh resolutions.
