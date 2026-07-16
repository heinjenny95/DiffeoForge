# Explicit blockwise Gaussian primitives

Status: **complete explicit public workflow path; direct-plan tile-recompute evidence; performance presets remain unvalidated**

Tracked prospectively by [primitive issue
#40](https://github.com/heinjenny95/DiffeoForge/issues/40) and [full-objective
issue #42](https://github.com/heinjenny95/DiffeoForge/issues/42).
Tile recomputation is tracked prospectively by
[engine issue #48](https://github.com/heinjenny95/DiffeoForge/issues/48).

## Why this slice exists

The dense correctness baseline constructs pairwise XYZ differences with shape
`query_rows × source_rows × 3`. Surface attachment also constructs dense
face-pair kernels and, for Varifold, a dense orientation matrix. That direct
implementation is easy to inspect but its quadratic intermediate memory is a
known barrier for simplified high-face-count meshes.

The blockwise functions evaluate the same all-pairs mathematics in explicit
tiles. They do not truncate neighborhoods, approximate kernels, change the
Gaussian convention, or silently switch algorithms.

## Public primitive contract

The engine exports:

- `GaussianTilePlan`;
- `TileAutogradStrategy`;
- `gaussian_convolve_blockwise`;
- `gaussian_convolve_gradient_blockwise`;
- `current_squared_distance_blockwise`; and
- `varifold_squared_distance_blockwise`.

Every operation requires positive `query_tile_size` and `source_tile_size`
arguments. For float64, the declared maximum single XYZ-difference tile is:

```text
query_tile_size × source_tile_size × 3 × 8 bytes
```

For example, a `1024 × 1024` tile declares a 24 MiB XYZ-difference tensor,
independent of total face count. Kernel, coefficient/orientation, output,
Python, PyTorch allocator, and retained trajectory memory still exist. In
particular, standard autograd may retain intermediates from multiple tiles
until backward completes. Version 0.1 therefore proves a bound on the largest
single pairwise tile allocation, not bounded total or peak RAM.

Current tiles convolve source normals and accumulate their inner product with
query normals. Varifold tiles calculate local area, orientation-similarity,
and Gaussian matrices, then accumulate a scalar. No complete face-by-face
kernel or orientation matrix is materialized.

## Opt-in full-objective contract

The low-level deformation energy, shooting, and point-flow functions, as well
as `subject_objective`, `atlas_objective`, and `optimize_atlas`, accept the
keyword-only argument `gaussian_tile_plan`. The default is exactly `None` and
retains the dense correctness path. A caller must construct and pass a
`GaussianTilePlan` explicitly to select blockwise execution, for example:

```python
plan = GaussianTilePlan(query_rows=256, source_rows=512)
result = subject_objective(..., gaussian_tile_plan=plan)
```

There is no automatic threshold, inferred tile size, environment-variable
override, or fallback between algorithms. The same declared plan controls
every Gaussian deformation, flow, Current, and Varifold operation reached by
that objective or optimizer call. Invalid plan types fail before numerical
integration begins.

## Direct-plan tile-recompute contract

The four low-level blockwise primitive functions additionally accept the
keyword-only choice `autograd_strategy="standard"` or
`autograd_strategy="recompute"`. Standard is the unchanged default. Recompute
uses PyTorch's non-reentrant activation checkpointing around each deterministic
tile calculation: the forward graph retains tile inputs and reconstructs
pairwise differences, kernels, coefficients, and orientation values when
backward needs them.

```python
value = gaussian_convolve_blockwise(
    x,
    y,
    weights,
    kernel_width,
    query_tile_size=256,
    source_tile_size=256,
    autograd_strategy="recompute",
)
```

`GaussianTilePlan` owns the same explicit strategy as its third field. A direct
engine caller can therefore carry recompute through deformation energy,
shooting, point flow, Current/Varifold attachment, complete Subject/Atlas
objectives, and the block optimizer:

```python
plan = GaussianTilePlan(256, 256, autograd_strategy="recompute")
result = atlas_objective(..., gaussian_tile_plan=plan)
```

This remains an engine-level prototype. Public `PairwiseEvaluationPlan`,
`modern-init`, YAML, manifests, `modern-run`, workload reports, and benchmarks
continue to construct standard-autograd tile plans only. There is no automatic
activation, environment override, or public workflow setting. Invalid or
misspelled strategies fail rather than falling back.

## Numerical contract and evidence

The algorithm is non-approximate, but source-tile accumulation changes
floating-point reduction order relative to one dense matrix multiplication.
Parity is therefore tolerance-based, not byte identity.

Tests currently require:

- forward and autograd-gradient parity for random `7 × 5` Gaussian
  convolution across `1 × 1`, uneven, and larger-than-input tiles;
- forward and second-derivative parity for the explicit Gaussian x-gradient;
- Current and Varifold forward/vertex-gradient parity on a tetrahedral mesh;
- Current/Varifold forward parity on the open 320-face CC0 meshes;
- unchanged orientation and joint-translation contracts; and
- runtime instrumentation proving every observed pair tile stays within the
  declared row/column bounds;
- full Current and Varifold subject trajectory, endpoint, objective-component,
  and template/control-point/momenta-gradient parity; and
- two-subject atlas objective/all-parameter-gradient parity plus one complete
  optimizer-cycle decision-history and final-parameter parity for both
  attachment types;
- recompute forward/gradient parity across uneven Gaussian tile shapes;
- recompute parity for the explicit Gaussian x-gradient and its differentiated
  result, plus Current/Varifold vertex gradients; and
- saved-tensor-hook instrumentation showing that the tested recompute
  convolution forward retains no rank-3 pairwise tensor and a smaller logical
  saved-tensor payload than standard tiling;
- Current and Varifold complete Subject trajectories, objective components,
  and template/control-point/momenta gradients under both standard and
  recompute plans;
- a two-subject Atlas objective and one complete optimizer-cycle decision and
  final-parameter comparison under both plans; and
- a 320-face CC0 Current-objective probe with `64 × 64` tiles: recompute retains
  no `64 × 64 × 3` tensor and has a smaller largest and summed logical saved
  payload while objective and all parameter gradients match standard exactly
  on the tested CPU run.

The dense path remains the correctness oracle and continues to match the
frozen Deformetrica primitive/objective evidence. `modern-run` can select the
same plan explicitly and records it in both immutable manifests. Subject
reconstructions, PCA endpoints, and mesh-quality evidence use the declared
mode. `modern-plan` and `modern-benchmark` v0.2 also accept it: their strict
reports bind the configured tile sizes to exact workload accounting and to
the measured fresh-process objective/gradient path.

## Gates before workflow integration

1. ~~extend the workload and benchmark schemas/models;~~ completed in v0.2;
2. benchmark several prospectively declared tile sizes using the measured
   protocol on representative simplified meshes;
3. measure the complete-objective recompute plan in fresh processes, including
   its additional backward compute, before exposing public configuration or
   deciding whether a custom backward pass is preferable; and
4. select evidence-based safe presets separately from user overrides.

Blockwise mode is selectable only by an explicit user plan. It must not become
an automatic default or claim a safe preset until the remaining gates pass.
Saved-tensor hooks describe tensors requested by autograd under the tested
PyTorch implementation; their logical byte sum is not unique storage, allocator
state, process RSS, total live memory, runtime performance, or 300-subject
feasibility.
