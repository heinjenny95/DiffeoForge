# Modern dense-engine workload planning

Status: **implemented operation model; not a runtime or peak-memory predictor**

Tracked prospectively by
[engineering issue #34](https://github.com/heinjenny95/DiffeoForge/issues/34).

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

## Exact dense-operation model

One *pair element* is one entry of a dense Gaussian kernel matrix. Let:

- `S` be the subject count;
- `C` be the control-point count;
- `Vt` and `Ft` be template points and faces;
- `Fs` be one subject's face count; and
- `L = timepoints - 1` be the integration-step count.

For each subject, one objective forward evaluates attachment pair elements

```text
Ft² + Fs² + Ft × Fs
```

for template self, subject self, and template/subject cross terms. Current and
Varifold attachments make the same three Gaussian calls; Varifold additionally
forms orientation-similarity matrices with the same pair dimensions.

The current implementation makes these additional dense Gaussian calls per
subject:

- shooting: `2 × C²` per Euler step or `6 × C²` per RK2 step;
- template flow: `Vt × C` per Euler step or `2 × Vt × C` per Heun step;
- `deformetrica_heun`: one final extrapolation containing `4 × C²`;
- deformation energy: one `C²` call.

The six RK2 shooting calls include two calculations currently performed before
the RK2 helper plus four inside it. This is a model of observable code, not an
idealized algorithm; an implementation change must update the versioned model
and instrumentation test.

The optimizer performs one initial objective/gradient evaluation. In the worst
configured line-search case its evaluation bound is

```text
1 + max_cycles × 3 parameter blocks × (1 + max_line_search_iterations)
```

Convergence, stationary blocks, accepted early line-search steps, or failure
can reduce the actual count. The report multiplies this bound by the exact
pair-element count of one objective forward; it does not translate operations
into seconds. This optimizer bound excludes final reconstruction and PCA-
endpoint flows, PCA SVD, mesh-quality verification, reporting, and file I/O;
the report states that exclusion as a warning.

## Known tensor payloads

The report calculates exact byte counts for selected visible payloads:

- initial float64 vertices, control points, and momenta plus int64 triangle
  connectivity passed to the engine;
- subject trajectories and flowed-template paths retained by one objective;
- the largest single dense float64 kernel matrix dimension; and
- its explicit `rows × columns × 3 × 8` XYZ-difference tensor.

Their arithmetic subtotal is useful for catching obviously impossible plans,
but it is **not peak RAM**. PyTorch autograd saves intermediates; kernel
construction creates additional matrices; the allocator can retain blocks;
Python/NumPy objects, reports, operating-system memory, and threaded numerical
libraries add overhead. Some allocations have different lifetimes.

The report records detected physical memory and output-filesystem free space.
If a known payload alone exceeds physical memory, it emits a warning. Passing
that comparison is not evidence that the run fits.

## PCA and output bound

The maximum retained momenta-PCA dimension is
`min(subjects - 1, 3 × control_points)`, further limited by the reviewed
`pca_components`. The report records the requested upper bound for retained
components, PCA endpoint components, PCA meshes, and all bundle VTK meshes.
Numerical rank or zero-variance axes can reduce actual endpoint output.

PCA and deformation component requests that exceed the cohort/feature limit
now fail before optimizer execution. This prevents a manually edited YAML from
running an expensive atlas only to fail during final bundle creation.

## Evidence and maintenance rule

Tests cover every supported combination of Current/Varifold, Euler/RK2
shooting, and Euler/Heun/Deformetrica-Heun flow. They wrap the real
`gaussian_kernel`, count every observed matrix dimension during an actual
objective forward, and require exact equality with the planning formula.

The JSON is validated against the bundled strict schema
`modern-workload-v0.1.json`. Configuration and input SHA-256 values tie the
plan to reviewed bytes. Live host observations can change over time; operation
counts remain deterministic for fixed configuration and mesh dimensions.

## Scientific boundary

This plan describes the current dense CPU/float64 correctness implementation.
It is not a benchmark, a wall-time forecast, a peak-RAM estimate, evidence that
300 specimens are feasible, a GPU model, or a Deformetrica resource model.
Measured scaling experiments on representative simplified meshes remain a
separate prospective gate.
