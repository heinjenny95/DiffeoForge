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

The current backend does **not** use the holdout for selection. Fixed-template
registration support is required before those untouched subjects can provide a
real generalization estimate. Training reconstruction error is never relabeled
as heldout error.

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

Even the strongest state still requires fixed-template heldout registration,
an independent anatomy-specific criterion, and a final locked full-cohort
atlas before strong manuscript language is justified.

## Desktop workflow

Open a verified Deformetrica result and choose **Open Validation Lab** on the
Results & PCA page. DiffeoForge creates or resumes one study next to the
pilot-calibrated configuration. The dialog shows only the next action and a
compact progress summary; design details and limitations are available behind
info disclosures. Cancellation retains completed immutable runs.

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
```

The output contains a SHA-bound manifest, append-only hash-chained event
ledger, immutable candidate configurations and runs, and JSON plus HTML final
reports.

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
