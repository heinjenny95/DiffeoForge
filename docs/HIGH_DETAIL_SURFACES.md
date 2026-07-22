# High-detail surface workflow foundation

Status: **explicit 10,000-face pre-compute contract implemented; production
performance and multiresolution optimization not yet validated**

Tracked by [engineering issue #177](https://github.com/heinjenny95/DiffeoForge/issues/177).

## What is implemented

DiffeoForge accepts supported VTK triangle surfaces at their supplied
resolution. It does not silently simplify, decimate, subdivide, or remesh them.
Project review records the template face count, the subject face-count range,
the exact largest logical all-pairs problem, and the largest execution tile.

The desktop setup offers two explicit Modern CPU execution choices:

- **Dense — small pilot / correctness baseline** constructs complete pairwise
  matrices and remains the numerical oracle.
- **Blockwise 256 × 256 — high-face-count experiment** evaluates the same
  Gaussian all-pairs mathematics in deterministic tiles. It is not a
  neighborhood truncation or approximation.

The selected mode and tile sizes are written into the versioned configuration,
workload evidence, run manifest, and result bundle. There is no hidden
face-count threshold, environment override, or fallback between modes.

## Reproducible 10,000-face evidence

The automated high-detail planning test constructs a closed, consistently
oriented 5,002-point sphere with exactly 10,000 triangular faces. It then runs
the production VTK parser, topology and triangle-quality gates, Modern project
initializer, strict schema validation, and configured-engine workload planner.

For that input, the largest surface-attachment pair has dimensions
`10,000 × 10,000`. Its conservative dense-equivalent float64 XYZ payload is
`10,000 × 10,000 × 3 × 8 = 2,400,000,000` bytes. The explicit `256 × 256`
blockwise plan declares a largest per-tile equivalent of
`256 × 256 × 3 × 8 = 1,572,864` bytes. The centered matrix kernel does not
materialize either rank-3 tensor; these values preserve auditable planning
arithmetic while the total number of logical pair interactions remains
unchanged.

This test proves configuration, parsing, quality control, provenance, and exact
pre-compute accounting for a 10,000-face surface. It does **not** execute or
validate a complete 10,000-face atlas.

## Scientific and engineering boundary

The tile figure is a conservative dense-equivalent, not an observed allocation
or total live memory. Standard PyTorch autograd may retain graphs from multiple
tiles; trajectories, mesh tensors, rank-2 kernels, the allocator, BLAS, Python,
and the operating system add further memory. Logical work remains quadratic in
face count, so avoiding rank-3 differences does not by itself make a
300-subject run fast.

No tile size is currently claimed to be universally safe. The desktop label
calls the route experimental, the workload page keeps peak RAM and runtime
unknown, and high-face-count review adds an explicit benchmark warning.

## Gates to a production high-detail workflow

1. Freeze representative pilot cohorts at approximately 1,500, 5,000, and
   10,000 faces with recorded simplification provenance.
2. Run prospective fresh-process benchmarks for declared tile shapes and
   autograd strategies on the intended Windows CPU hardware.
3. Measure full pilot atlases, not only objective/gradient microbenchmarks,
   including optimizer convergence and result verification.
4. Compare atlas and PCA stability across mesh resolutions.
5. Design and validate a coarse-to-fine optimizer that transfers parameters
   between resolutions without changing the declared scientific model.
6. Only then choose evidence-based defaults or expose a production preset.

Until these gates pass, users should begin with a small representative pilot,
retain the exact workload and benchmark artifacts, and treat the blockwise
10,000-face route as engineering capability rather than production validation.
