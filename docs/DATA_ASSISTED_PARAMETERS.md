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

### Matching resolution (attachment width)

The researcher first states what the surface-fit measurement should notice.
This controls the matching resolution; it does not control how far a modeled
deformation spreads.

| Intent | Nominal attachment width |
| --- | ---: |
| Notice small ridges, pits, and edges (fine) | `0.025 D` |
| Balance small features and overall form | `0.05 D` |
| Judge mainly broad overall form (coarse) | `0.10 D` |

The conservative four-edge sampling diagnostic is:

```text
min(0.5, max(0.005, 4 × cohort median sampled edge length / cohort median diagonal))
```

This value is **not a hard lower bound**. Recommendation version 0.1 used it to
raise the proposed attachment width automatically. Version 0.2 retains the
researcher's declared or measured anatomical scale and uses the edge-based
value to broaden the pilot search. The automatic pilot therefore tests values
on both sides whenever possible. This prevents mesh sampling from being ignored
without pretending that one universal multiple of edge length determines the
scientifically correct varifold/current kernel.

### Deformation reach and control points

The researcher separately states how far a modeled movement should spread
through neighboring regions. This controls deformation reach; it does not
control which surface details contribute to the fit measurement.

| Intent | Proposed deformation width |
| --- | ---: |
| Keep changes confined to small regions (local) | `0.05 D` |
| Mix local changes and broad coordinated movement | `0.10 D` |
| Make wider regions move together (broad) | `0.20 D` |

The two decisions are independent. A study can, for example, ask matching to
notice a small spur while still requiring the surrounding structure to deform
smoothly as a broad coordinated region.

Initial control-point spacing is set equal to the deformation width. This
matches the documented Deformetrica initialization convention and keeps the
relationship explicit. Smaller values create rapidly more control points and
must be benchmarked.

### Noise and optimization

Noise standard deviation is not inferred from mesh geometry. The current
configuration seed is explicitly labelled provisional and is set to one
quarter of the proposed attachment ratio only so that a complete pilot
configuration can be produced. It must be calibrated from registration
residuals and sensitivity runs; optional pilot visual correspondence can add
context when the automatic trade-off is unclear.

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

## Transparent pilot-calibration plan

After geometry analysis, the desktop can now create a versioned, hash-bound
calibration plan. The researcher may first measure the smallest biologically
relevant feature directly on the 3D template. DiffeoForge then:

1. selects a deterministic geometry-descriptor medoid and farthest-first
   extremes from the subjects;
2. performs a logarithmically spaced **joint screen** of attachment width and
   deformation width/control spacing, spanning both the declared anatomical
   center and mesh-sampling diagnostics;
3. refines deformation width/control spacing after the joint screen;
4. tests a wider logarithmic noise-weight range;
5. tests 10/20/30 time points for numerical accuracy;
6. records subject-level residuals, reconstruction-wide validity and area
   distortion, convergence, regularity, runtime, and raw alternatives;
7. perturbs all metric weights, independently aggregates metric ranks, and
   deterministically bootstraps pilot subjects before allowing an automatic
   selection.

An automatic stage choice is allowed only when the same Pareto candidate has a
clear score margin, wins at least 75% of the predeclared weight scenarios,
agrees with the independent rank aggregation, and—when subject-level evidence
is available—wins at least 70% of the deterministic subject bootstraps. If
these criteria are not met, DiffeoForge reports `sensitive` or `ambiguous` and
refuses to invent a unique winner.

The pilot-subject heuristic covers geometric diversity only. It cannot infer
biological strata that are absent from mesh coordinates. A manuscript study
must therefore confirm representation of relevant groups and may replace or
augment the selected pilot cohort with a predeclared stratified selection.

The exported JSON, HTML, and SHA-256 sidecar explicitly say
`planned_not_executed`. Creating the plan does not run Deformetrica, choose a
winner, or approve parameters. Project creation embeds the full plan beneath
the recommendation provenance, and recomputes the plan fingerprint before
accepting it.

See [Transparent Deformetrica parameter calibration](PARAMETER_CALIBRATION.md)
for the complete staged protocol and command-line reproduction.

## Evidence still required

Only executed pilot evidence can convert a starting proposal into a
dataset-specific parameter justification. The plan requires:

- objective and component histories;
- registration residual distributions;
- automatic mesh-quality inspection and optional pilot visual QC;
- deformation smoothness and plausibility;
- runtime, memory, and control-point count;
- stability of the atlas and PCA under neighboring settings;
- robustness of the winner to metric priorities and pilot-subject resampling;
- a final full-resolution, full-cohort confirmation.

Skipping pilot visual QC does not waive the manuscript-stage full-cohort
inspection and confirmation requirements.

Automated candidate execution and result ingestion remain a separate
implementation and validation step. Until that exists, the exported plan is a
pre-registration aid rather than an automatic optimizer.
