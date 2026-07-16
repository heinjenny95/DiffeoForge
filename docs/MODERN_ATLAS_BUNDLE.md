# Immutable modern atlas result bundle

Status: **tested v0.1 engineering contract embedded in the experimental workflow**

Tracked prospectively by
[engineering issue #26](https://github.com/heinjenny95/DiffeoForge/issues/26) and
[PCA-product issue #30](https://github.com/heinjenny95/DiffeoForge/issues/30),
with output-quality gates tracked by
[scientific-change issue #32](https://github.com/heinjenny95/DiffeoForge/issues/32).

## Purpose

An in-memory optimizer result is not sufficient scientific evidence. Bundle
v0.1 turns the experimental modern-engine state into an independently readable
directory whose parameters, reconstructed meshes, optimizer history, PCA
inputs, and integrity metadata remain available without a live Python session.

The bundle is deliberately separate from the existing Deformetrica prepared-
run schema. The experimental modern workflow embeds it, but it does not
pretend that the modern engine is already a validated production backend.

## Directory contract

```text
bundle/
  bundle-manifest.json
  bundle-manifest.sha256
  atlas/
    estimated-template.vtk
  parameters/
    control-points.csv
    momenta.csv
  optimization/
    history.csv
  reconstructions/
    subject-0000-<safe-label>.vtk
    ...
  analysis/
    pca-summary.json
    pca-scores.csv
    pca-loadings.csv
    pca-mean.csv
    pca-scree.svg
    pca-scores.svg
    pca-deformations.json
    pca-deformations/
      mean-momenta.vtk
      pc-0001-minus.vtk
      pc-0001-plus.vtk
      ...
  quality/
    mesh-quality.json
    mesh-quality.csv
```

VTK files are deterministic legacy ASCII PolyData with double-precision point
text and the estimated template connectivity. CSV files use UTF-8 and LF line
endings. Floats use 17 significant digits so they round-trip to binary64.
Exact subject labels live in the manifest. Reconstruction filenames include a
zero-padded input index plus a sanitized label, so Unicode transliteration
collisions cannot overwrite one another.

CSV cells beginning with spreadsheet formula characters (`=`, `+`, `-`, or
`@`) receive a leading apostrophe. The exact unescaped label remains in JSON.
This prevents an identifier from becoming an executable spreadsheet formula
when a CSV is opened interactively.

## Atomic creation and verification

`write_modern_atlas_bundle` requires a destination that does not exist. It
writes into a private sibling directory, validates the completed manifest, and
renames that directory into place. A failure removes the temporary directory;
the requested destination is never left partially populated. Existing output
is never overwritten.

The manifest lists every payload file with byte size and SHA-256. Its own bytes
are covered by `bundle-manifest.sha256`. Verification requires:

- a valid bundled JSON Schema;
- a matching manifest sidecar;
- exactly the listed files and no additional files;
- matching size and SHA-256 for every artifact;
- safe bundle-relative POSIX paths;
- readable triangular VTK geometry with manifest-declared point/face counts;
- recomputed topology and triangle-shape evidence for every generated VTK; and
- recomputed local face-area ratios relative to the estimated template.

SHA-256 detects changes but is not an authenticity signature. Anyone able to
replace both data and hashes can forge a new internally consistent bundle.
Future signed releases are a separate distribution concern.

## PCA handoff

Bundle creation automatically applies `momenta_pca` to the final subject-by-
control-point-by-XYZ momenta tensor. It stores:

- feature space and exact sample/feature labels;
- component count, numerical rank, singular values, explained variance and
  ratios, tied groups, zero-variance components, and sign convention;
- subject scores;
- component loadings;
- the PCA mean vector;
- a static SVG scree plot and PC1/PC2 score plot (or explicit PC1 strip); and
- a mean-momenta mesh plus selected nonzero ±PC deformation meshes.

The CSV mean and loading files plus the declared sign convention are sufficient
to reproduce projections without a serialized Python object. PCA failure, such
as zero total subject variance, fails bundle creation explicitly rather than
emitting meaningless axes.

Each PC endpoint uses `mean ± k * sqrt(explained_variance) * loading` in the
stored control-point-then-XYZ order. The explicit positive amplitude `k` and
requested component count are inputs to bundle creation and are recorded in
both the manifest and `pca-deformations.json`. Numerical zero-variance axes are
listed and skipped instead of producing duplicate, misleading meshes. Every
SVG, JSON, and VTK is covered by the exact artifact inventory. Verification
also parses the static SVGs, rejects scripts/external references, cross-checks
the deformation definition against the manifest, and validates every
deformation mesh's geometry counts.

## Mesh-quality evidence

The bundle's JSON and CSV quality reports cover the estimated template, every
subject reconstruction, the mean-momenta mesh, and both endpoints of each
emitted nonzero PCA axis. The default structural gates reject duplicate faces,
isolated vertices, non-manifold edges, inconsistent orientation, and zero-area
faces. Optional triangle-angle, edge-ratio, and local face-area-ratio thresholds
are carried from the reviewed workflow configuration.

Verification rebuilds the report from the stored VTK geometry and rejects a
report or CSV whose values differ, even if an actor also refreshed artifact and
manifest hashes. Exact definitions and excluded failure modes are documented
in [deterministic mesh-quality evidence](MESH_QUALITY.md).

## Python entry point

```python
from diffeoforge.modern_bundle import (
    ModernAtlasModelSettings,
    verify_modern_atlas_bundle,
    write_modern_atlas_bundle,
)

settings = ModernAtlasModelSettings(
    deformation_kernel_width=0.6,
    attachment_kernel_width=0.45,
    noise_variance=0.01,
    number_of_time_points=5,
)
bundle = write_modern_atlas_bundle(
    "results/modern-atlas-001",
    optimization_result,
    template_triangles,
    subject_labels,
    settings,
    pca_deformation_standard_deviations=2.0,
    pca_deformation_components=3,
)
manifest = verify_modern_atlas_bundle(bundle)
```

Bundle v0.1 accepts only detached CPU float64 optimizer results and CPU `int64`
triangle connectivity. This is the validated correctness boundary, not a
silent limitation to be removed without new evidence.

## Scientific boundary and next gates

The bundle makes experimental results auditable. It does not make the optimizer
scientifically validated, guarantee complete surface validity, establish Deformetrica
equivalence, or prove that momenta PCA is appropriate for a particular
biological hypothesis.

The [experimental modern workflow](MODERN_WORKFLOW.md) now embeds and verifies
this bundle after folder preflight and optimization. Remaining gates are
lifecycle/checkpoint integration, schema migration policy, self-intersection
and rendering checks, matched Deformetrica result comparison, biological PCA
validation, and large-cohort performance validation.
