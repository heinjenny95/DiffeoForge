# DiffeoForge Validation Lab

The Validation Lab is the post-pilot evidence layer for Deformetrica parameter
selection. It does not claim that one parameter set is universally best. Its
strongest automatic conclusion is deliberately narrower:

> The same finalist was preferred robustly within a frozen, neighboring
> parameter search space when the training-cohort composition changed.

## Why this is separate from pilot calibration

Pilot calibration explores attachment width, deformation width/control-point
spacing, noise, and integration accuracy. Reusing the same pilot runs as final
validation would reward the parameters on the data that selected them. The
Validation Lab therefore:

1. requires a completed pilot-calibrated configuration;
2. freezes the pilot-selected values and their nearest tested more-local and
   smoother neighbors;
3. reserves a deterministic, geometry-diverse holdout before execution;
4. compares every finalist on the same non-heldout training cohort;
5. repeats the comparison on predeclared deterministic training resamples; and
6. produces one scoped uncertainty report only after every frozen run finishes.

After the training/resampling comparison completes, DiffeoForge creates a
separate SHA-bound holdout study. For each finalist it copies the estimated
training-only template and control points, freezes both, and estimates only the
heldout-subject momenta. The same reserved subjects are registered against every
frozen finalist. Training reconstruction error is never relabeled as heldout
error, and the original Validation Lab manifest and report remain unchanged.

## Common external evidence

Finalists are compared using evidence that has the same definition for every
parameter set:

- symmetric, deterministically sampled vertex-to-triangle surface-distance p95;
- p95 absolute log triangle-area distortion relative to the initial template;
- invalid-face count across the atlas and reconstructions;
- explicit Deformetrica tolerance-stop evidence; and
- preference stability across the full training comparison and frozen
  resamples.

Deformetrica's internal attachment and regularity magnitudes are not used as a
universal cross-kernel score. Runtime is reported, but it is not an anatomical
quality metric.

The practical surface-error equivalence margin is 5% of a researcher-measured
smallest relevant feature when available. Without that measurement, the lab
uses 0.5% of the template diagonal as an explicitly numerical fallback and
warns that it is not a biological threshold.

## Confidence states

- `incomplete`: at least one frozen run is absent;
- `failed_validity_gate`: at least one finalist did not converge, produced
  invalid geometry, or lacks a common external metric;
- `ambiguous`: no finalist wins 60% of completed cohort comparisons;
- `sensitive`: a finalist wins at least 60% but less than 80%;
- `robust_within_search_space`: one finalist wins at least 80% of the complete
  predeclared comparisons and all required runs pass automatic validity gates.

The separate fixed-template holdout reports:

- `failed_validity_gate`: at least one frozen registration lacks valid common
  evidence;
- `ambiguous_on_holdout`: no finalist wins 60% of paired subject comparisons;
- `sensitive_on_holdout`: support is at least 60% but below 80%;
- `heldout_preference_identified`: support reaches 80%, but the training study
  had no unique prior winner to confirm;
- `confirmed_on_holdout`: at least 80% support and agreement with the training
  preference; or
- `training_preference_not_confirmed`: at least 80% support for a different
  finalist.

Even the strongest holdout state still requires an independent anatomy-specific
criterion and a final locked full-cohort atlas before strong manuscript language
is justified.

## PCA stability evidence

DiffeoForge provides `compare_pca_stability` as a versioned numerical building
block for paired finalist or repeat analyses. It pairs specimens by their exact
labels and reports two complementary score-geometry measures:

- linear CKA, which is invariant to principal-component signs, orthogonal
  rotations, and a common score-scale change; and
- Spearman correlation of all paired inter-specimen score distances, which is
  also insensitive to monotone distance rescaling.

Direct loading-subspace principal angles are reported only when the declared
feature space, named feature identities, and selected subspace dimension match.
They are deliberately withheld when finalists use different control-point
systems; similarly numbered momenta coordinates are not assumed homologous.
Components are selected by a declared cumulative-variance target (90% by
default) or an explicit fixed count. The result contains no automatic pass
threshold and explicitly does not claim biological meaning or group
separation. Binding these measurements into newly versioned Validation Lab
study artifacts and prospectively calibrating thresholds remain separate work;
existing immutable studies are not reinterpreted retroactively.

Two already verified Deformetrica PCA bundles can be compared and bound into a
new immutable artifact now:

```powershell
diffeoforge reference-pca-stability `
  "C:\result-a\analysis\reference-result-analysis-v0.2" `
  "C:\result-b\analysis\reference-result-analysis-v0.2" `
  --output "C:\comparison\pca-stability" `
  --variance-target 0.90

diffeoforge reference-pca-stability-verify `
  "C:\comparison\pca-stability"
```

The verifier rechecks both complete PCA bundles, their source hashes, and the
exact stability calculation. Existing destinations are never replaced.

## Desktop workflow

Open a verified Deformetrica result and choose **Open Validation Lab** on the
Results & PCA page. DiffeoForge creates or resumes one study next to the
pilot-calibrated configuration. After the training comparison, the same dialog
prepares and runs the fixed-template holdout extension. Before execution it
states the exact run and registration count, iteration cap, broad time and disk
planning ranges, and safe-cancellation behavior. During execution it shows the
active run, first-iteration activity, logged optimizer iteration, elapsed time,
and a live ETA. Cancellation retains completed immutable runs.

## Reproducible command-line workflow

```powershell
diffeoforge reference-validation-study-init `
  "C:\project\atlas-calibrated.yaml" `
  --output "C:\project\diffeoforge-validation-lab" `
  --holdout-fraction 0.20 `
  --resamples 5 `
  --resample-fraction 0.80

diffeoforge reference-validation-study-run `
  "C:\project\diffeoforge-validation-lab"

diffeoforge reference-validation-study-status `
  "C:\project\diffeoforge-validation-lab" --json

diffeoforge reference-holdout-study-init `
  "C:\project\diffeoforge-validation-lab"

diffeoforge reference-holdout-study-run `
  "C:\project\diffeoforge-validation-lab\heldout-confirmation"

diffeoforge reference-holdout-study-status `
  "C:\project\diffeoforge-validation-lab\heldout-confirmation" --json
```

The output contains a SHA-bound manifest, append-only hash-chained event
ledger, immutable candidate configurations and runs, and JSON plus HTML final
reports.

The holdout extension has its own immutable manifest, digest, event ledger, run
specifications, and JSON/HTML report. It binds the parent study manifest, parent
training report, training-run result inventories, estimated templates, estimated
control points, and exact heldout mesh bytes by SHA-256.

## Independent synthetic ground truth

The lab also supplies an analytic benchmark generator that does not use
Deformetrica to create its truth. It creates local, global, and mixed smooth
deformations while retaining exact ordered vertex correspondence:

```powershell
diffeoforge reference-validation-synthetic-create `
  "C:\meshes\template.vtk" `
  --output "C:\validation\analytic-ground-truth" `
  --subjects-per-family 6

diffeoforge reference-validation-synthetic-evaluate `
  "C:\recovered\subject.vtk" `
  "C:\validation\analytic-ground-truth\truth-mixed-01.vtk"
```

Analytic truth tests correspondence recovery under known deformations. It does
not reproduce every biological structure, segmentation artifact, or sampling
regime and therefore cannot replace independent real-data validation.
