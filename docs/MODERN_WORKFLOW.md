# Experimental modern mesh-folder workflow

Status: **tested CPU/float64 engineering path; not scientifically validated or production-scaled**

Tracked prospectively by
[engineering issue #28](https://github.com/heinjenny95/DiffeoForge/issues/28).

## Purpose

The modern numerical functions previously accepted only in-memory tensors.
Workflow v0.1 connects a normal directory of triangular legacy VTK PolyData
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
diffeoforge modern-run modern-atlas.yaml
diffeoforge modern-verify modern-atlas-run
```

The geometry-scaled values produced by `modern-init` are visibly labelled
exploratory. They are starting values, not biologically or numerically
validated presets.

## End-to-end contract

For every run, DiffeoForge:

1. resolves the template and subject glob in stable filename order;
2. preflights and hashes every selected VTK file;
3. copies the raw source bytes into a private temporary run directory;
4. reads both float/double vertices and complete triangle connectivity from
   supported ASCII or big-endian binary legacy VTK PolyData;
5. optionally applies recorded landmark-derived Procrustes transforms to
   copied full-mesh vertices;
6. selects shared initial control points with the configured deterministic
   farthest-template-vertex rule and initializes all momenta to zero;
7. executes the declared dense CPU/float64 atlas optimizer;
8. creates and verifies the nested immutable atlas/PCA bundle;
9. verifies the outer workflow schema, exact file inventory, hashes, raw and
   aligned geometry, effective configuration, and nested bundle; and
10. atomically renames the temporary directory to the requested destination.

Any failure before publication removes the temporary directory. Existing
destinations are never overwritten or reused.

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
  result/
    atlas-bundle/
      bundle-manifest.json
      atlas/estimated-template.vtk
      reconstructions/*.vtk
      parameters/*.csv
      optimization/history.csv
      analysis/pca-*.csv
      analysis/pca-summary.json
```

The outer manifest stores exact source filenames and subject order, raw-input
SHA-256 values and geometry counts, aligned paths, the selected template
vertex indices used as control points, runtime thread count and seed, and the
hash of the nested bundle manifest. Absolute source paths are intentionally
not copied into the public manifest.

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

## Deterministic initialization

`farthest_template_vertices` begins with the template vertex farthest from the
template centroid. Each next control point is the lowest-index vertex with the
greatest distance to its nearest selected vertex. There is no random sample.
The exact selected vertex indices are stored in the workflow manifest.

This is a reproducible engineering initialization, not evidence that the
selected count or locations are optimal for a scientific dataset.

## Verification and limits

`modern-verify` rejects schema violations, a changed manifest sidecar,
modified/missing/additional files, duplicate or unsafe paths, symbolic links,
changed raw/aligned geometry counts, invalid effective configuration,
inconsistent preprocessing evidence, invalid initialization indices, and any
failure of the nested atlas-bundle verifier.

SHA-256 provides integrity detection, not an authenticity signature. Workflow
v0.1 also does not provide checkpoints, modern-engine resume, PLY/STL/OBJ
input, mesh repair, self-intersection tests, PCA plots, PC deformation
visualizations, a GUI, or an installer. The five-subject CC0 regression path is
not evidence of Deformetrica equivalence, biological validity, global
convergence, GPU parity, or acceptable runtime and memory for 300+ specimens.
