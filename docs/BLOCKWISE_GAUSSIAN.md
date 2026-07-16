# Explicit blockwise Gaussian primitives

Status: **implemented isolated primitives; not enabled in atlas workflows**

Tracked prospectively by
[engineering issue #40](https://github.com/heinjenny95/DiffeoForge/issues/40).

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
  declared row/column bounds.

The dense path remains the correctness oracle and continues to match the
frozen Deformetrica primitive/objective evidence. The blockwise path is not yet
used by `subject_objective`, `optimize_atlas`, `modern-run`, `modern-plan`, or
`modern-benchmark`.

## Gates before workflow integration

1. thread tile sizes through the full subject/atlas objective without hidden
   defaults;
2. extend the workload model and immutable configuration/run schemas;
3. prove full objective, parameter-gradient, optimizer-history, endpoint,
   PCA, and mesh-quality parity against dense mode;
4. benchmark several explicit tile sizes using the measured protocol; and
5. determine whether checkpoint/recomputation or a custom backward pass is
   required to reduce retained autograd memory; and
6. select evidence-based safe presets separately from user overrides.

Only after those gates may blockwise mode become a selectable atlas backend.
