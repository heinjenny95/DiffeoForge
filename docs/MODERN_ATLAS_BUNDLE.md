# Immutable modern atlas result bundle

Status: **tested v0.1 engineering contract; not yet a workflow backend**

Tracked prospectively by
[engineering issue #26](https://github.com/heinjenny95/DiffeoForge/issues/26).

## Purpose

An in-memory optimizer result is not sufficient scientific evidence. Bundle
v0.1 turns the experimental modern-engine state into an independently readable
directory whose parameters, reconstructed meshes, optimizer history, PCA
inputs, and integrity metadata remain available without a live Python session.

The bundle is deliberately separate from the existing Deformetrica prepared-
run schema. It does not pretend that the modern engine is already a selectable
production backend.

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
- readable triangular VTK geometry with manifest-declared point/face counts.

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
- the PCA mean vector.

The CSV mean and loading files plus the declared sign convention are sufficient
to reproduce projections without a serialized Python object. PCA failure, such
as zero total subject variance, fails bundle creation explicitly rather than
emitting meaningless axes.

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
)
manifest = verify_modern_atlas_bundle(bundle)
```

Bundle v0.1 accepts only detached CPU float64 optimizer results and CPU `int64`
triangle connectivity. This is the validated correctness boundary, not a
silent limitation to be removed without new evidence.

## Scientific boundary and next gates

The bundle makes experimental results auditable. It does not make the optimizer
scientifically validated, guarantee mesh quality, establish Deformetrica
equivalence, or prove that momenta PCA is appropriate for a particular
biological hypothesis.

The [experimental modern workflow](MODERN_WORKFLOW.md) now embeds and verifies
this bundle after folder preflight and optimization. Remaining gates are
lifecycle/checkpoint integration, schema migration policy, mesh-quality
metrics, PCA plots and PC deformation visualizations, matched Deformetrica
result comparison, and large-cohort performance validation.
