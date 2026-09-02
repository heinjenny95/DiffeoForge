# Verified Deformetrica result analysis and deformation-kernel PCA

Status: **connected source-level analysis path; not yet scientifically validated**

A completed DiffeoForge Deformetrica run can now produce a self-contained PCA
snapshot from Deformetrica's estimated subject initial momenta. The desktop does
this automatically after parent verification succeeds. The same operation is
available without the GUI:

```powershell
diffeoforge reference-pca RUN_DIRECTORY
diffeoforge reference-pca-verify `
  RUN_DIRECTORY/analysis/reference-result-analysis-v0.3 `
  --source-run RUN_DIRECTORY
```

Neither command edits the completed run outputs. The default destination is a
new, non-replacing directory at
`RUN_DIRECTORY/analysis/reference-result-analysis-v0.3`. An existing
destination is refused. Legacy `reference-momenta-pca` snapshots remain
readable and are never upgraded in place. Version 0.2 Cartesian snapshots also
remain verifiable.

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

## Prospective PC deformation Shooting

Reference PCA deformation meshes use Deformetrica itself rather than silently
substituting the Modern Engine. The first step is deliberately non-executing:

```powershell
diffeoforge reference-pca-deformation-design RUN_DIRECTORY `
  --output C:\path\to\new-shooting-design `
  --components 3 `
  --standard-deviations 2

diffeoforge reference-pca-deformation-design-verify `
  C:\path\to\new-shooting-design `
  --source-run RUN_DIRECTORY

diffeoforge reference-pca-deformation-run `
  C:\path\to\new-shooting-design

diffeoforge reference-pca-deformation-verify `
  RUN_DIRECTORY\analysis\reference-pca-deformations-v0.1-result `
  --source-run RUN_DIRECTORY
```

The prospective design copies and binds the estimated Deformetrica template
and control points, derives exact mean and ±PC momenta from the verified PCA,
changes only the source model type to `Shooting`, preserves the source
deformation and integration settings, and records the exact source runtime.
Its status is `prospective_not_executed`: creating or verifying it starts no
process and makes no endpoint-mesh claim. The separate execution command uses
the exact source launcher/thread/device contract for one `deformetrica compute`
operation, captures stdout and stderr, refuses an existing destination, and
publishes only after every final-timepoint surface has the source template's
point and triangle counts. Its verifier rechecks the nested prospective design,
source hashes, exact inventory, endpoint identities, file hashes, and VTK
topology. Runtime completion remains engineering evidence, not biological
validation. The default result location is detected by the desktop, which then
adds the verified mean and ±PC surfaces to the existing native 3D viewer.

For a completed Deformetrica result, the source desktop also exposes this as
`Generate verified PC shape meshes…`. The action first reuses and verifies an
existing default design or creates a new immutable design for at most PC1–PC3 at
±2 standard deviations, then runs the exact source runtime on a background
worker. The window reports elapsed time, remains open until the subprocess has
stopped, and reloads the complete result only after the new result inventory,
hashes, endpoint identities, and VTK topology pass verification. Failure leaves
the previously verified result loaded and never restarts automatically. The CLI
remains the explicit interface for other component counts or endpoint distances.

Subject identity and order come from the immutable run manifest's subject input
records. This is the same order used when DiffeoForge wrote Deformetrica's
dataset XML. Features are flattened in this declared order:

1. subject;
2. shared control point;
3. Cartesian X, Y, Z.

## Analysis method

The default is deterministic tangent-momenta PCA in the fitted Deformetrica
deformation-kernel metric. For control points `q` and deformation width `w`,
DiffeoForge uses Deformetrica's Gaussian convention
`K(q_i,q_j) = exp(-||q_i-q_j||² / w²)` and the vector-valued metric
`K tensor I3`. PCA is performed in a numerically whitened representation, while
the stored inverse components reconstruct exact momenta that can be passed to
Deformetrica Shooting. The bundle records the source width, kernel convention,
and control-point hash.

The maximum retained component count is `min(subjects - 1, metric rank)`;
`--components` can request a smaller explicit count. The stored sign convention
makes the largest-absolute reconstructed momenta loading positive, with the
lowest feature index used for ties. Component signs remain conventional.

Legacy Cartesian momenta PCA remains an explicit option:

```powershell
diffeoforge reference-pca RUN_DIRECTORY --method cartesian_momenta_pca `
  --output C:\path\to\new-cartesian-comparison
```

Generic RBF KernelPCA is not the default. It changes with its bandwidth and has
no automatic inverse to shootable momenta. DiffeoForge exposes it only inside a
named sensitivity comparison alongside PCoA, Isomap, and diffusion maps:

```powershell
diffeoforge reference-shape-space-comparison RUN_DIRECTORY
diffeoforge reference-shape-space-comparison-verify `
  RUN_DIRECTORY/analysis/reference-shape-space-comparison-v0.1
```

The comparison tests RBF gamma at 0.5, 1, and 2 times the median-distance
heuristic, records distance fidelity, optimally scaled stress, centered-kernel
alignment, and outlier overlap, and exports method scores. LDDMM tangent PCoA is
an independent distance-based cross-check. Isomap and diffusion maps are
exploratory views. Exact geodesic PGA is documented as not executed because it
requires additional fitting or shooting rather than cost-free post-processing.

## Published evidence

The atomic bundle contains:

- byte-for-byte copies of raw Deformetrica momenta and control points;
- byte-for-byte copies of the objective-history CSV and terminal log;
- normalized open CSV tables with subject and control-point identity;
- a deterministic convergence SVG with the last logged iteration, configured
  maximum, runtime, and bounded terminal stop evidence;
- PCA summary, scores, loadings, and mean as JSON/CSV;
- static script-free scree, PC1/PC2, and, when available, PC2/PC3 SVGs;
- a complete artifact inventory with byte counts and SHA-256 hashes;
- source run manifest, result, and output-inventory hashes; and
- a versioned manifest plus its own SHA-256 sidecar.

Verification checks the exact inventory, raw parameter hashes and dimensions,
recomputes the PCA from the copied raw values, regenerates the convergence SVG,
and compares the resulting statistics and tables. Supplying `--source-run`
additionally requires the current source run to match the recorded hashes,
objective history, terminal log, and subject order.

Deformetrica 4.3 applies an accepted step before testing its internal
objective-change tolerance, but does not print that final accepted step when
the test triggers. Consequently, a tolerance-stopped curve ends at the
preceding logged state. DiffeoForge records this explicitly and does not turn
the internal stop signal into a claim of adequate registration or scientific
convergence.

## Scientific boundary

This PCA is an exploratory coordinate summary. It does not prove adequate atlas
registration, optimizer convergence, group separation, taxonomic structure,
biological effect, or causality. The current reference result viewer
exposes executed mean/positive/negative PC deformation meshes only when their
separate Shooting result exists at the default location and passes full
verification. Covariate-aware plots and inferential statistics likewise
require separate methods and validation decisions.
