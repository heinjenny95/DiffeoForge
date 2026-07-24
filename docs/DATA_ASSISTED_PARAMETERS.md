# Data-assisted Deformetrica parameter guidance

## Purpose

DiffeoForge must not present one static parameter set as scientifically
recommended for every surface cohort. The desktop workflow therefore delays
Deformetrica parameter guidance until the selected meshes are in the coordinate
frame that will be used for atlas estimation.

The accepted alignment bases are:

1. **DiffeoForge GPA** — the exact transforms from a converged, hash-bound,
   explicitly approved landmark-Procrustes preview;
2. **declared GPA** — a researcher declaration that translation, rotation, and
   the intended size treatment were completed before import.

Coordinate diagnostics can warn about remaining centroid or scale dispersion.
They cannot prove landmark homology or that an external GPA was biologically
appropriate.

## Scientific boundary

The Deformetrica literature distinguishes parameters that encode scientific
scale choices:

- the attachment/current/varifold kernel controls the spatial detail at which
  surfaces are compared;
- the deformation kernel controls the distance over which points move in a
  correlated manner, hence the locality or rigidity of the deformation;
- the data weight or noise parameter controls the trade-off between regularity
  and fidelity to the observations.

Those boundaries are normally set in relation to the anatomical features of
interest and then checked with registrations. They are not recoverable from
file validity or triangle count alone. See Durrleman et al.,
[Registration, Atlas Estimation and Variability Analysis of White Matter Fiber Bundles Modeled as Currents](https://publications.sci.utah.edu/publications/durrleman10/Durrleman_NImg10.pdf),
and the
[Deformetrica model configuration manual](https://gitlab.com/icm-institute/aramislab/deformetrica/-/wikis/3_user_manual/3.2_model_xml_file/diff?version_id=dc5d83d56374a380f961e55ee06a0eaf9594bfbc&view=parallel).

DiffeoForge consequently separates:

- **automatic observations** from aligned mesh geometry;
- **researcher decisions** about anatomical detail and deformation locality;
- **pilot-calibrated parameters** that cannot be justified from geometry alone.

## Read-only geometry analysis

For the template and every selected subject, DiffeoForge reads the complete
triangle geometry and measures, after any approved GPA transform:

- bounding-box diagonal;
- vertex centroid and root-mean-square radius;
- point and triangle count;
- median positive edge length from a deterministic sample of at most 20,000
  triangles per mesh.

It then reports:

- template diagonal and cohort median diagonal;
- coefficient of variation of aligned bounding-box diagonals;
- root-mean-square centroid dispersion divided by cohort median diagonal;
- cohort median sampled edge length divided by cohort median diagonal.

Every source is read without modification. A SHA-256 change observed during the
analysis fails the operation.

## Current transparent proposal rules

All ratios below are relative to the aligned template bounding-box diagonal
`D`.

### Attachment width

The researcher states the surface detail to preserve:

| Intent | Nominal attachment width |
| --- | ---: |
| Fine anatomical detail | `0.025 D` |
| Balanced anatomical detail | `0.05 D` |
| Coarse/global surface detail | `0.10 D` |

The mesh-sampling floor is:

```text
min(0.5, max(0.005, 4 × cohort median sampled edge length / cohort median diagonal))
```

The proposed attachment ratio is the larger of the stated nominal ratio and
this floor. This does not discover the correct anatomical scale. It prevents a
requested spatial resolution from silently falling below an explicit,
reproducible sampling diagnostic.

### Deformation width and control points

The researcher states the scale of biological variation:

| Intent | Proposed deformation width |
| --- | ---: |
| Local differences | `0.05 D` |
| Balanced local/global differences | `0.10 D` |
| Global differences | `0.20 D` |

Initial control-point spacing is set equal to the deformation width. This
matches the documented Deformetrica initialization convention and keeps the
relationship explicit. Smaller values create rapidly more control points and
must be benchmarked.

### Noise and optimization

Noise standard deviation is not inferred from mesh geometry. The current
configuration seed is explicitly labelled provisional and is set to one
quarter of the proposed attachment ratio only so that a complete pilot
configuration can be produced. It must be calibrated from registration
residuals, visual correspondence, and sensitivity runs.

Maximum iterations (`150`), initial step size (`0.01`), and convergence
tolerance (`0.0001`) are also pilot settings rather than geometry-derived
scientific recommendations. Early stopping, final residuals, surface quality,
and neighboring parameter values must be inspected.

## Recorded provenance

A data-assisted `atlas.yaml` records:

- recommendation algorithm version and SHA-256 fingerprint;
- alignment basis and approved GPA fingerprint where applicable;
- selected surface-detail and deformation-scale intents;
- template identity, mesh/subject counts, and geometry measurements;
- all proposed ratios;
- automatic inferences, researcher decisions, warnings, and required pilot
  validations.

The record supports exact reconstruction of what DiffeoForge proposed and why.
It does not turn the proposal into scientific validation.

## Required next validation

For a manuscript-scale workflow, DiffeoForge should next automate a small,
predeclared calibration grid on representative specimens. That study should
compare neighboring attachment/deformation widths and noise values using:

- objective and component histories;
- registration residual distributions;
- visual and mesh-quality inspection;
- deformation smoothness and plausibility;
- runtime, memory, and control-point count;
- stability of the atlas and PCA under neighboring settings.

Only that evidence can convert a starting proposal into a dataset-specific
parameter justification.
