# PCA of atlas-derived subject features

Status: **tested analysis prototype; not yet an atlas output command**

Tracked by [scientific-change issue #19](https://github.com/heinjenny95/DiffeoForge/issues/19).

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
passes the detached subject momenta directly into `momenta_pca`, establishing
the intended optimizer-to-analysis boundary without calling it a complete
scientific atlas workflow.

## Remaining gates

Before PCA becomes a user-facing atlas product, DiffeoForge still needs the
complete template/control-point atlas estimator, immutable feature extraction,
run-manifest references, CSV/JSON output schemas, score/loading plots, PC shape
visualization through reconstructed deformations, missing-subject handling,
and validation on predeclared biological data. The paper must state the feature
space, centering, component retention, scaling/alignment policy, and treatment
of tied or rank-deficient directions.
