# PCA of atlas-derived subject features

Status: **tested experimental analysis product in the modern workflow; not scientifically validated**

Core PCA is tracked by
[scientific-change issue #19](https://github.com/heinjenny95/DiffeoForge/issues/19);
plots and deformation products are tracked prospectively by
[issue #30](https://github.com/heinjenny95/DiffeoForge/issues/30).

## Feature space is part of the result

"PCA of shape" is incomplete unless the input representation is named. PCA of
raw vertices, Procrustes coordinates, deformed template endpoints, Cartesian
initial momenta, and kernel-metric tangent vectors are different analyses.

The first DiffeoForge helper implements PCA of per-subject initial momenta in
this fixed flattening order:

1. specimen order supplied by the atlas run;
2. shared control-point order;
3. Cartesian `x`, `y`, `z` within each control point.

Its result declares the feature space as
`subject_initial_momenta_cartesian` and stores every sample and feature label.
This representation is meaningful only when all subjects use the same atlas
template, control points, coordinate frame, kernel convention, and units.

## Mathematical contract

`diffeoforge.analysis.principal_component_analysis` centers a float64
sample-by-feature matrix and computes its singular value decomposition. For
`n` samples, explained variance is `singular_value^2 / (n - 1)`. The reported
total variance includes the complete centered matrix even when only a subset of
components is retained.

SVD component signs are arbitrary. DiffeoForge makes the stored result
repeatable by requiring the loading with greatest absolute value to be
positive; an exact tie uses the lowest feature index. Exact or tolerance-level
tied singular values are reported as component-index groups because individual
axes within a tied subspace are not scientifically identifiable. Numerically
zero retained components and the numerical rank are also explicit.

The result provides projection, inverse projection, and training-data
reconstruction. Arrays are read-only evidence copies. At full centered rank,
the training feature matrix reconstructs within floating-point tolerance.

## Validation

Tests compare explained variances to covariance-matrix eigenvalues, verify full
reconstruction and new-sample projection, separate retained from total
variance, freeze momenta feature ordering, detect tied/zero-variance
components, enforce the sign convention, and verify deterministic non-mutating
behavior. Invalid shapes, dtypes, labels, component counts, non-finite values,
and zero total variance fail explicitly.

An integration test optimizes momenta for three synthetic surface targets and
passes the detached subject momenta directly into `momenta_pca`. The
[modern atlas bundle](MODERN_ATLAS_BUNDLE.md) now persists the same declared
feature order as a JSON summary plus CSV scores, loadings, and mean vector and
tests those files against the in-memory PCA arrays.

The bundle also writes two dependency-light static SVGs: a scree plot of the
retained explained-total-variance ratios and a PC1/PC2 subject-score plot. If
only PC1 is retained, the latter is explicitly a one-dimensional PC1 strip; a
second axis is never invented. Subject identifiers are stored as escaped SVG
text/tooltips, and the files contain no scripts or external resources.

For geometric inspection, the workflow reconstructs the endpoint of the mean
momenta and both directions of selected nonzero components. For component
`i`, its two initial-momenta vectors are exactly

```text
mean ± k * sqrt(explained_variance_i) * component_loading_i
```

where `k` is the explicit `analysis.deformation_standard_deviations` setting.
The selected component count is `analysis.deformation_components`; `null`
means all retained components. `modern-init` chooses the first three (or fewer
when the cohort permits fewer) as a visible, editable starting value to avoid
hundreds of unnecessary mesh products in a large cohort. The bundle records
the equation, effective settings, feature order, sign convention, written
paths, and any numerical zero-variance components skipped.

## Remaining gates

The experimental [modern workflow](MODERN_WORKFLOW.md) invokes, visualizes, and
records this PCA automatically. Before it becomes a validated scientific
product, DiffeoForge still needs missing-subject handling, loading-focused
views, mesh rendering/quality evidence, and validation on predeclared
biological data. The paper must state the feature space, centering, component
retention, deformation amplitude, scaling/alignment policy, and treatment of
tied or rank-deficient directions. PC signs are conventional; ± endpoints are
not observed specimens, confidence intervals, or biological effects.
