# Modern configured-engine workload planning

Status: **implemented operation model; not a runtime or peak-memory predictor**

Tracked prospectively by
[engineering issue #34](https://github.com/heinjenny95/DiffeoForge/issues/34)
and extended for configured blockwise execution by
[engineering issue #46](https://github.com/heinjenny95/DiffeoForge/issues/46).

## User path

After reviewing the YAML created by `modern-init`, generate a workload plan
without starting optimization:

```powershell
diffeoforge modern-plan modern-atlas.yaml
```

The default destination is `modern-atlas.workload/` next to the configuration:

```text
modern-atlas.workload/
  workload.json
  workload.html
```

JSON is the full machine-readable record. HTML is a self-contained review
view. The directory is written privately and renamed into place only after both
files succeed. It is never overwritten by default. `--force` replaces only a
directory with exactly the two recognized generated report files; unrelated
user directories are rejected.

The command reads the reviewed configuration and selected VTK metadata. It
does not construct PyTorch tensors, evaluate the atlas objective, or start the
optimizer.

## Exact all-pairs operation model

One *pair element* is one logical entry of the exact Gaussian all-pairs
calculation. Dense and blockwise execution perform the same number of logical
pair interactions; blockwise execution partitions them into tiles. Let:

- `S` be the subject count;
- `C` be the control-point count;
- `Vt` and `Ft` be template points and faces;
- `Fs` be one subject's face count; and
- `L = timepoints - 1` be the integration-step count.

For each subject, one objective forward evaluates attachment pair elements

```text
Ft^2 + Fs^2 + Ft * Fs
```

for template self, subject self, and template/subject cross terms. Current and
Varifold attachments make the same three Gaussian calls; Varifold additionally
forms orientation-similarity values with the same logical pair dimensions.

The current implementation makes these additional Gaussian calls per subject:

- shooting: `2 * C^2` per Euler step or `6 * C^2` per RK2 step;
- template flow: `Vt * C` per Euler step or `2 * Vt * C` per Heun step;
- `deformetrica_heun`: one final extrapolation containing `4 * C^2`;
- deformation energy: one `C^2` call.

The six RK2 shooting calls include two calculations currently performed before
the RK2 helper plus four inside it. This is a model of observable code, not an
idealized algorithm; an implementation change must update the versioned model
and instrumentation test.

The optimizer performs one initial objective/gradient evaluation. In the worst
configured line-search case its evaluation bound is

```text
1 + max_cycles * 3 parameter blocks * (1 + max_line_search_iterations)
```

Convergence, stationary blocks, accepted early line-search steps, or failure
can reduce the actual count. The report multiplies this bound by the exact
logical pair-element count of one objective forward; it does not translate
operations into seconds. This optimizer bound excludes final reconstruction
and PCA-endpoint flows, PCA SVD, mesh-quality verification, reporting, and file
I/O; the report states that exclusion as a warning.

## Logical pairs versus execution tiles

The report records two deliberately different maxima:

- `largest_logical_pair` is the largest complete all-pairs problem reached by
  one operation; and
- `largest_execution_tile` is the largest pairwise matrix dimension evaluated
  at once by the configured plan.

For dense mode these dimensions are equal. For blockwise mode the execution
rows and columns are exactly `min(logical_rows, query_tile_size)` and
`min(logical_columns, source_tile_size)` for every candidate operation, with
the largest resulting tile reported. The model therefore preserves the total
logical work while exposing the configured execution dimensions. It does not
infer a tile size, switch algorithms, or treat fewer evaluated rows as fewer
mathematical interactions.

## Conservative tensor-payload equivalents

The report calculates exact byte counts for selected visible tensors and
versioned dense-equivalent payloads:

- initial float64 vertices, control points, and momenta plus int64 triangle
  connectivity passed to the engine;
- subject trajectories and flowed-template paths retained by one objective;
- the largest logical all-pairs float64 matrix dimension; and
- the conservative dense-equivalent
  `tile_rows * tile_columns * 3 * 8` XYZ-difference payload for the largest
  dense or blockwise execution dimensions.

The versioned v0.2 JSON field names retain
`float64_xyz_difference_tensor_bytes` for backward compatibility. Since the
centered matrix-kernel optimization, ordinary Gaussian forward evaluation does
not materialize a `rows × columns × 3` difference tensor: it constructs
rank-2 distance/kernel matrices from centered norms and matrix multiplication.
The XYZ values are therefore conservative dense-equivalent planning numbers,
not observed allocations. Analytical Gaussian x-gradients still need explicit
differences.

Their arithmetic subtotal remains useful as stable conservative accounting,
but it is **not peak RAM**. PyTorch autograd saves intermediates and standard
blockwise backward can retain graphs from multiple tiles until the gradient
completes; kernel construction creates rank-2 matrices; the allocator can
retain blocks; Python/NumPy objects, reports, operating-system memory, and
threaded numerical libraries add overhead. Some allocations have different
lifetimes.

The report records detected physical memory and output-filesystem free space.
If a conservative equivalent alone exceeds physical memory, it emits a
warning. Passing that comparison is not evidence that the run fits.

## PCA and output bound

The maximum retained momenta-PCA dimension is
`min(subjects - 1, 3 * control_points)`, further limited by the reviewed
`pca_components`. The report records the requested upper bound for retained
components, PCA endpoint components, PCA meshes, and all bundle VTK meshes.
Numerical rank or zero-variance axes can reduce actual endpoint output.

PCA and deformation component requests that exceed the cohort/feature limit
fail before optimizer execution. This prevents a manually edited YAML from
running an expensive atlas only to fail during final bundle creation.

## Evidence and maintenance rule

Tests cover every supported combination of Current/Varifold, Euler/RK2
shooting, and Euler/Heun/Deformetrica-Heun flow. They instrument both centered
matrix-kernel and explicit analytical-gradient paths, count every observed
logical pair dimension during an actual objective forward, and require exact
equality with the planning formula.
Separate blockwise tests bind the configured tile plan to the reported engine
and require the execution dimensions and byte arithmetic to remain exact.

The JSON is validated against the bundled strict schema
`modern-workload-v0.2.json`. Additional semantic validation rejects inconsistent
inventory counts, pair and tile arithmetic, payload subtotals, or optimizer
bounds. Configuration and input SHA-256 values tie the plan to reviewed bytes.
Live host observations can change over time; operation counts remain
deterministic for fixed configuration and mesh dimensions.

## Scientific boundary

This plan describes the configured exact dense or blockwise CPU/float64
implementation. It is not a benchmark, a wall-time forecast, a peak-RAM
estimate, evidence that 300 specimens are feasible, a GPU model, or a
Deformetrica resource model. A blockwise tile record is a conservative
dense-equivalent payload, not proof of an allocation and not a bound on total
live autograd memory. Measured scaling experiments on representative simplified
meshes remain a separate prospective gate.
`modern-benchmark` provides the first narrow objective/gradient measurement
protocol; it does not convert this plan into a runtime predictor. See
[modern benchmark protocol](MODERN_BENCHMARK.md).
