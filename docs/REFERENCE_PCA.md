# Verified PCA of Deformetrica momenta

Status: **connected source-level analysis path; not yet scientifically validated**

A completed DiffeoForge Deformetrica run can now produce a self-contained PCA
snapshot from Deformetrica's estimated subject initial momenta. The desktop does
this automatically after parent verification succeeds. The same operation is
available without the GUI:

```powershell
diffeoforge reference-pca RUN_DIRECTORY
diffeoforge reference-pca-verify `
  RUN_DIRECTORY/analysis/reference-momenta-pca `
  --source-run RUN_DIRECTORY
```

Neither command edits the completed run outputs. The default destination is a
new, non-replacing directory at
`RUN_DIRECTORY/analysis/reference-momenta-pca`. An existing destination is
refused.

## Accepted source contract

The importer first runs the complete terminal-run verifier. Its output
inventory must list exactly one filename ending in
`__EstimatedParameters__Momenta.txt` and exactly one ending in
`__EstimatedParameters__ControlPoints.txt`. Every output file must still match
its inventoried path, byte count, and SHA-256, and no unlisted output file may
be present.

The momenta parser then requires Deformetrica's three-integer header:

```text
subject_count control_point_count dimension
```

Only dimension three is accepted. The remaining finite numeric rows must match
`subject_count * control_point_count` exactly. Blank separator lines are
allowed; missing, extra, nonnumeric, or non-finite rows fail. The separate
control-point file must contain exactly the declared number of finite XYZ rows.

Subject identity and order come from the immutable run manifest's subject input
records. This is the same order used when DiffeoForge wrote Deformetrica's
dataset XML. Features are flattened in this declared order:

1. subject;
2. shared control point;
3. Cartesian X, Y, Z.

## Analysis method

The transparent default is centered linear PCA using deterministic `float64`
SVD. The maximum retained component count is `min(subjects - 1, features)`;
`--components` can request a smaller explicit count. The stored sign convention
makes the largest-absolute loading positive, with the lowest feature index used
for ties. Component signs remain conventional.

This deliberately differs from the legacy local notebook, which applied an RBF
KernelPCA with a fixed `gamma=0.25`. DiffeoForge does not silently preserve that
undocumented scientific choice. A future kernel method must be exposed as a
separately named, parameterized, validated option.

## Published evidence

The atomic bundle contains:

- byte-for-byte copies of raw Deformetrica momenta and control points;
- normalized open CSV tables with subject and control-point identity;
- PCA summary, scores, loadings, and mean as JSON/CSV;
- static script-free scree, PC1/PC2, and, when available, PC2/PC3 SVGs;
- a complete artifact inventory with byte counts and SHA-256 hashes;
- source run manifest, result, and output-inventory hashes; and
- a versioned manifest plus its own SHA-256 sidecar.

Verification checks the exact inventory, raw parameter hashes and dimensions,
recomputes the PCA from the copied raw values, and compares the resulting
statistics and tables. Supplying `--source-run` additionally requires the
current source run to match the recorded hashes and subject order.

## Scientific boundary

This PCA is an exploratory coordinate summary. It does not prove adequate atlas
registration, optimizer convergence, group separation, taxonomic structure,
biological effect, or causality. The current reference path does not yet create
mean/positive/negative PC deformation meshes, registration-quality renderings,
covariate-aware plots, or inferential statistics. Those require separate
methods and validation decisions.
