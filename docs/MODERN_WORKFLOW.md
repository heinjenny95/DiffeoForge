# Experimental modern mesh-folder workflow

Status: **tested CPU/float64 path and five-subject-qualified CUDA/float64 path; not scientifically
validated or production-scaled**

Tracked prospectively by
[engineering issue #28](https://github.com/heinjenny95/DiffeoForge/issues/28) and
[PCA-product issue #30](https://github.com/heinjenny95/DiffeoForge/issues/30),
with mesh-quality gates tracked by
[scientific-change issue #32](https://github.com/heinjenny95/DiffeoForge/issues/32) and
blockwise workflow provenance tracked by
[engineering issue #44](https://github.com/heinjenny95/DiffeoForge/issues/44).

## Purpose

The modern numerical functions previously accepted only in-memory tensors.
Configuration v0.6 and workflow manifest v0.1 connect a normal directory of
triangular legacy VTK PolyData
meshes to the full atlas optimizer and the immutable atlas/PCA bundle without
requiring a notebook, XML, or a special working directory.

The workflow has two deliberately separate steps. `modern-init` inspects the
selected meshes and writes a complete, editable YAML configuration. It does
not start computation. `modern-run` revalidates that configuration and creates
one immutable run at a previously nonexistent destination.

```powershell
python -m pip install -e ".[modern-engine]"

diffeoforge modern-init "C:\path\to\meshes" `
  --units millimeter `
  --template "C:\path\to\meshes\template.vtk" `
  --config modern-atlas.yaml

# Review every value in modern-atlas.yaml before computation.
diffeoforge modern-plan modern-atlas.yaml
# Review modern-atlas.workload/workload.html before computation.
diffeoforge modern-run modern-atlas.yaml
diffeoforge modern-verify modern-atlas-run
```

The geometry-scaled values produced by `modern-init` are visibly labelled
exploratory. They are starting values, not biologically or numerically
validated presets.

The direct CLI workflow remains a VTK contract. The guided desktop can first
read triangular PLY, OBJ, or STL surfaces for landmarking and reviewed GPA,
preserve byte-identical raw copies, and point this workflow at the resulting
canonical `aligned-vtk/` cohort. See
[surface input formats](SURFACE_INPUT_FORMATS.md).

The generated runtime section always declares exact pairwise evaluation:

```yaml
runtime:
  device: cpu
  precision: float64
  threads: 1
  random_seed: 20260715
  pairwise_evaluation:
    mode: dense
    query_tile_size: null
    source_tile_size: null
    autograd_strategy: standard  # optional for standard execution
```

To select the already parity-tested non-approximate blockwise engine without
editing YAML, pass `--pairwise-mode blockwise --query-tile-size N
--source-tile-size M` to `modern-init`. Both sizes are mandatory positive row
counts; dense mode requires both to remain null. There is no automatic size,
threshold, environment override, or fallback. Legacy v0.1 configurations and
manifests without this record remain readable only as dense; configuration
v0.2 through v0.6 require it. Configuration v0.3 may additionally declare
`autograd_strategy: recompute` for blockwise execution. This preserves the
exact forward and gradient result while recomputing pairwise intermediates
during backward to reduce retained memory; the extra calculation is explicit
in both engine identity and immutable provenance.

Configuration v0.4 additionally makes optimizer step initialization explicit.
`fixed` restarts every block search from its declared starter step, preserving
the original behavior. `previous_accepted` starts the next visit to that block
from its last accepted step and therefore avoids deterministically repeating
known oversized candidates. Every accepted step remains in optimizer history.
V0.4 can also initialize momenta from a canonical
`subject_label,control_point,x,y,z` CSV. The exact subject order, control-point
count, finite values, copied bytes, and SHA-256 are checked before execution and
again during workflow verification.

Configuration v0.5 may bind one verified exact-state checkpoint and its parent
effective configuration. Current Engine 1.5 runs write checkpoint v0.3 with
separate L-BFGS histories for every configured block. This is reserved for immutable completed-run
continuation and guarded abandoned-run recovery. Preflight verifies exact
Engine, runtime/thread, model, optimizer, subject, and numerical-state identity
before deserializing the non-executable optimizer tensor store.

Configuration v0.6 additionally requires an explicit shared-parameter step
convention. New configurations use `inverse_subject_count`, which divides only
the template and control-point starter steps by cohort size while preserving
the complete summed objective and subject-specific momenta step. Legacy
configurations retain `none`. See
[cohort-invariant shared-parameter steps](MODERN_SHARED_STEP_SCALING.md).

Engine 1.3 may additionally declare `momenta_updates_per_cycle`. Its default is
one. A larger value deterministically visits subject-local Momenta repeatedly
before the next configured shared block while preserving one separate L-BFGS
history per unique block. Progress, workload bounds, bundles, benchmarks, and
checkpoint bindings record the expanded schedule explicitly. See
[experimental multi-rate atlas optimization](MODERN_MULTIRATE_OPTIMIZATION.md).

Engine 1.4 may additionally declare `subject_batch_workers` when
`subject_batch_size` is finite. Independent subject batches execute concurrently,
then return to the main optimizer in frozen batch order. One worker is the
backward-compatible default. Workflow, bundle, workload, benchmark, and
checkpoint evidence bind both settings; continuation cannot change either.
See [parallel subject batching](MODERN_SUBJECT_BATCHING.md).

Engine 1.5 adds an explicit experimental `runtime.device: cuda` path. It uses
float64 throughout, disables TF32, requests deterministic PyTorch algorithms,
requires one subject-batch worker, synchronizes CUDA before benchmark timing,
records CUDA allocator telemetry, and serializes canonical CPU checkpoint and
bundle artifacts. A requested CUDA run fails before computation if CUDA is not
available; it never falls back silently. The generated default remains `cpu`.
Pass `--device cuda` to `modern-init` only inside an explicitly reviewed CUDA
environment; the choice is written into YAML rather than inferred from hardware.
See [Engine 1.5 CUDA feasibility](MODERN_ENGINE15_CUDA.md).

New starter configurations set `checkpoint_interval_cycles: 5` and
`checkpoint_retention: latest`. A terminal cycle is always written. The
workflow manifest binds the effective policy and retained cycle sequence;
legacy configurations without either field retain every complete cycle.

New workflow and nested bundle manifests also record a Modern engine
`implementation_version` separately from the pairwise mode and general package
version. The two layers must agree. Older manifests without this optional field
remain verifiable; prospective continuation plans bind the implementation
revision expected for their successor.

A completed, verified run that reaches its cycle cap without convergence can be
continued through a separate hash-bound prospective successor. Engine 1.5
copies the exact complete-cycle numerical state, including per-block L-BFGS histories and
relative-objective baselines; it never modifies or relabels the parent. See
[verified Modern optimizer continuation](MODERN_CONTINUATION.md).

New runs also write hash-bound state after each complete optimizer cycle. These
checkpoints are verified inside a successful workflow and may survive a hard
process/machine failure inside the abandoned private directory. A guarded CLI
can freeze the latest verified complete cycle into a separate non-overwriting
prospective successor; it never resumes an active process or modifies the
source. See [Modern complete-cycle checkpoints](MODERN_CHECKPOINTS.md) and
[guarded Modern checkpoint recovery](MODERN_CHECKPOINT_RECOVERY.md).

`modern-plan` v0.2 is a non-compute review step for the configured exact
engine. It publishes logical all-pairs operation counts, the largest logical
pair, the largest dense or blockwise matrix dimensions evaluated by the
reviewed plan, and conservative dense-equivalent payload arithmetic. It does
not predict allocations, peak RAM, or runtime. See
[modern workload planning](MODERN_WORKLOAD.md).

During `modern-run`, the CLI prints live stage and optimizer-decision events.
They come from the same versioned application-service callback transported by
the source-level desktop worker. A decision event is emitted only after the
optimizer has committed an initial, accepted, stationary, or failed record;
rejected line-search candidates are not shown as accepted progress. See
[modern progress events](MODERN_PROGRESS.md) and the
[desktop worker protocol](DESKTOP_WORKER.md).

For an optional measured CPU microbenchmark before a full run, choose the
subject prefix explicitly:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml --subjects 5
```

This measures fresh-process objective/gradient repeats using the same declared
dense or blockwise plan, not the complete optimizer or workflow. A blockwise
benchmark may additionally override standard/recompute explicitly. See the
[modern benchmark protocol](MODERN_BENCHMARK.md).

## End-to-end contract

For every run, DiffeoForge:

1. resolves the template and subject glob in stable filename order;
2. preflights and hashes every selected VTK file;
3. creates a versioned private marker and process-held lease, then copies the
   raw source bytes into that private temporary run directory;
4. reads both float/double vertices and complete triangle connectivity from
   supported ASCII or big-endian binary legacy VTK PolyData;
5. optionally applies recorded landmark-derived Procrustes transforms to
   copied full-mesh vertices;
6. records and enforces deterministic topology and triangle-shape gates for
   every raw and effective input mesh;
7. selects shared initial control points with the configured deterministic
   farthest-template-vertex method, or copies and verifies an explicit finite
   three-column control-point file, and initializes momenta either to zero or
   from a strictly identity-bound v0.4 CSV;
8. executes the declared dense or exact blockwise CPU/float64 atlas optimizer;
9. creates and verifies the nested immutable atlas/PCA/quality bundle;
10. removes private-only marker/lease state, then verifies the outer workflow
   schema, exact file inventory, hashes, raw and
   aligned geometry, effective configuration, and nested bundle; and
11. atomically renames the temporary directory to the requested destination.

Any failure before publication removes the temporary directory. Existing
destinations are never overwritten or reused. A hard exit can bypass cleanup;
`modern-private-status DESTINATION` then performs exact-name read-only discovery
without deleting, renaming, resuming, or publishing. See
[private unpublished run discovery](PRIVATE_RUN_DISCOVERY.md).

## Run directory

```text
modern-atlas-run/
  workflow-manifest.json
  workflow-manifest.sha256
  config/
    source.yaml
    effective-config.json
  input/
    raw/
      template-0000-*.vtk
      subject-0001-*.vtk
      ...
    landmarks.csv                 # only when enabled
    aligned/*.vtk                 # only when enabled
  preprocessing/
    procrustes.json               # only when enabled
  quality/
    input-mesh-quality.json
    input-mesh-quality.csv
  checkpoints/
    cycle-000001/
      checkpoint.json
      checkpoint.sha256
      state/
        estimated-template.vtk
        control-points.txt
        momenta.csv
    ...
  result/
    atlas-bundle/
      bundle-manifest.json
      atlas/estimated-template.vtk
      reconstructions/*.vtk
      parameters/*.csv
      optimization/history.csv
      analysis/pca-*.csv
      analysis/pca-summary.json
      analysis/pca-scree.svg
      analysis/pca-scores.svg
      analysis/pca-deformations.json
      analysis/pca-deformations/*.vtk
      quality/mesh-quality.json
      quality/mesh-quality.csv
```

The outer manifest stores exact source filenames and subject order, raw-input
SHA-256 values and geometry counts, aligned paths, the selected template
vertex indices used as control points, runtime thread count and seed, and the
hash of the nested bundle manifest. Absolute source paths are intentionally
not copied into the public manifest.
Both outer and nested manifests store the pairwise mode and both tile sizes.
The outer verifier cross-checks that provenance against the hashed effective
configuration. The same plan is used for optimization, subject
reconstructions, and every PCA deformation endpoint.

## Optional labelled landmarks

Procrustes alignment is enabled only when a landmark file is explicitly
selected. The UTF-8 CSV header and column order are fixed:

```csv
mesh_file,landmark,x,y,z
template.vtk,anterior,0.0,1.0,0.0
template.vtk,dorsal,0.0,0.0,1.0
template.vtk,posterior,0.0,-1.0,0.0
subject-01.vtk,anterior,0.1,1.2,0.0
...
```

The template and every selected subject must have exactly the same ordered,
unique landmark labels. Mesh names must match the selected filenames exactly.
Unknown meshes, missing rows, duplicate labels, inconsistent order,
non-numeric/non-finite coordinates, fewer than three landmarks, degenerate
configurations, and nonconvergence all fail before atlas publication.

The template and subjects participate in one generalized-Procrustes cohort.
Scaling to unit centroid size is on and reflections are off in the generated
configuration, but both decisions remain explicit. `procrustes.json` stores
the coordinate convention, settings, ordered labels, consensus, convergence
history, residuals, and every centroid/scale/rotation transform. Both raw and
aligned mesh copies remain inspectable.

## Mesh-quality gates

`modern-init` writes explicit structural gates and optional numeric thresholds
into `quality_control`. The default rejects duplicate faces, isolated vertices,
non-manifold edges, inconsistent edge orientation, and zero-area faces. It
does not reject open surfaces or multiple face-connected components by
default. Numeric triangle-angle, edge-ratio, and local face-area-ratio limits
remain disabled until the study declares defensible values.

`modern-run` records both raw and effective input assessments. The nested
bundle assesses the estimated template, all reconstructions, and all emitted
PCA meshes; generated meshes are also compared face by face with the final
template when connectivity is identical. Both verifiers recompute the JSON and
CSV evidence from VTK geometry. See the exact definitions, configuration, and
limitations in [deterministic mesh-quality evidence](MESH_QUALITY.md).

## Deterministic initialization

`farthest_template_vertices` begins with the template vertex farthest from the
template centroid. Each next control point is the lowest-index vertex with the
greatest distance to its nearest selected vertex. There is no random sample.
The exact selected vertex indices are stored in the workflow manifest.

This is a reproducible engineering initialization, not evidence that the
selected count or locations are optimal for a scientific dataset.

## Automatic PCA products

The reviewed YAML makes both PCA retention and deformation visualization
explicit:

```yaml
analysis:
  pca_components: null
  deformation_standard_deviations: 2.0
  deformation_components: 3
```

`pca_components: null` retains every mathematically available PCA axis in the
CSV/JSON analysis. `deformation_components` limits the more expensive VTK
endpoint generation; `null` requests every retained axis. `modern-init` writes
three or fewer according to the cohort's maximum component count, avoiding an
accidental hundreds-of-mesh default for large cohorts. These are transparent
starting values, not validated biological choices.

The nested bundle includes a scree SVG, a PC1/PC2 scores SVG (or explicit PC1
strip), a mean-momenta mesh, and both directions of each requested nonzero PC.
All are deterministic, hashed, schema-declared, and reconstructed with the
run's final template/control points and exact flow settings.

## Verification and limits

`modern-verify` rejects schema violations, a changed manifest sidecar,
modified/missing/additional files, duplicate or unsafe paths, symbolic links,
changed raw/aligned geometry counts, invalid effective configuration,
inconsistent preprocessing evidence, invalid initialization indices, and any
failure of the nested atlas-bundle verifier.
It also rejects an engine id or pairwise plan that differs from the effective
configuration.

SHA-256 provides integrity detection, not an authenticity signature. Progress
counts are not runtime percentages and carry no ETA. Workflow
v0.1 now records complete-cycle checkpoint state and can freeze a separately
verified successor from an abandoned private run. Both crash recovery and its
completed-run continuation are new sequential workflows, not restoration of an
in-memory line-search state or a partial optimizer cycle.
It also does not provide PLY/STL/OBJ
input, mesh repair, self-intersection tests, loading plots, mesh rendering,
a GUI, or an installer. PCA signs are conventional and
±PC meshes are neither observations nor confidence intervals. The five-subject
CC0 regression path is not evidence of Deformetrica equivalence, biological
validity, global convergence, GPU parity, or acceptable runtime and memory for
300+ specimens.
