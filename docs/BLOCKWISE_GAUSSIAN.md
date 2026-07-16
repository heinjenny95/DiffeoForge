# Explicit blockwise Gaussian primitives

Status: **complete opt-in engine path; not enabled in public atlas workflows**

Tracked prospectively by [primitive issue
#40](https://github.com/heinjenny95/DiffeoForge/issues/40) and [full-objective
issue #42](https://github.com/heinjenny95/DiffeoForge/issues/42).

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
  attachment types.

The dense path remains the correctness oracle and continues to match the
frozen Deformetrica primitive/objective evidence. `modern-run` can now select
the same plan explicitly and records it in both immutable manifests. Subject
reconstructions, PCA endpoints, and mesh-quality evidence use the declared
mode. `modern-plan` and `modern-benchmark` v0.1 deliberately refuse blockwise
configurations until their models are versioned.

## Gates before workflow integration

1. extend the workload and benchmark schemas/models;
2. benchmark several explicit tile sizes using the measured protocol;
3. determine whether checkpoint/recomputation or a custom backward pass is
   required to reduce retained autograd memory; and
4. select evidence-based safe presets separately from user overrides.

Only after those gates may blockwise mode become a selectable atlas backend.
