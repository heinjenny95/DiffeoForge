# Experimental modern mesh-folder workflow

Status: **tested CPU/float64 engineering path; not scientifically validated or production-scaled**

Tracked prospectively by
[engineering issue #28](https://github.com/heinjenny95/DiffeoForge/issues/28) and
[PCA-product issue #30](https://github.com/heinjenny95/DiffeoForge/issues/30),
with mesh-quality gates tracked by
[scientific-change issue #32](https://github.com/heinjenny95/DiffeoForge/issues/32) and
blockwise workflow provenance tracked by
[engineering issue #44](https://github.com/heinjenny95/DiffeoForge/issues/44).

## Purpose

The modern numerical functions previously accepted only in-memory tensors.
Configuration v0.2 and workflow manifest v0.1 connect a normal directory of
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
```

To select the already parity-tested non-approximate blockwise engine without
editing YAML, pass `--pairwise-mode blockwise --query-tile-size N
--source-tile-size M` to `modern-init`. Both sizes are mandatory positive row
counts; dense mode requires both to remain null. There is no automatic size,
threshold, environment override, or fallback. Legacy v0.1 configurations and
manifests without this record remain readable only as dense; configuration
v0.2 requires it.

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
run may additionally declare a benchmark-only standard/recompute override; it
does not change `modern-run` or its provenance. See the
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
   farthest-template-vertex rule and initializes all momenta to zero;
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
v0.1 also does not provide checkpoints, modern-engine resume, PLY/STL/OBJ
input, mesh repair, self-intersection tests, loading plots, mesh rendering,
a GUI, or an installer. PCA signs are conventional and
±PC meshes are neither observations nor confidence intervals. The five-subject
CC0 regression path is not evidence of Deformetrica equivalence, biological
validity, global convergence, GPU parity, or acceptable runtime and memory for
300+ specimens.
