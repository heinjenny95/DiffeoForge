# DiffeoForge calibration evidence standard

## Claim boundary

DiffeoForge must never equate optimizer convergence with registration quality
or call one parameter set universally optimal. The strongest defensible claim
is dataset- and objective-specific:

> Within the predeclared search domain and validation criteria, DiffeoForge
> identified a Pareto-optimal parameter set whose preference was robust to
> reasonable metric priorities and pilot-subject resampling, and whose atlas
> and downstream statistics passed full-cohort sensitivity confirmation.

## Evidence levels

1. **Starter** — geometry-scaled values only; no executed registration evidence.
2. **Eligible** — completed and converged; no invalid atlas or reconstruction
   faces; all required metrics are finite.
3. **Sensitive** — an eligible Pareto winner exists but changes under reasonable
   metric weights, subject resampling, or independent rank aggregation.
4. **Robust pilot** — at least three eligible candidates; base winner has a
   score margin of at least 0.05, wins at least 75% of weight scenarios, agrees
   with weighted ranks, and wins at least 70% of subject bootstraps when those
   data are available.
5. **Full-cohort confirmed** — selected parameters and retained neighbors are
   compared on the complete cohort; registration outliers, atlas geometry,
   convergence, and PCA subspace stability pass predeclared tolerances.
6. **Externally validated** — independent homologous landmarks, synthetic known
   deformations, replicated cohorts, or another task-relevant ground truth
   corroborates the chosen correspondence scale.

Only levels 5–6 support strong scientific parameter-selection language. Level
4 permits automatic continuation but remains a pilot result.

## Current automatic metrics

- symmetric sampled nearest-vertex residual p95, both pooled and per subject;
- deterministic resampling sensitivity;
- final Deformetrica regularity magnitude as an optimizer comparison proxy;
- p95 absolute log triangle-area change pooled across the atlas and every
  reconstruction relative to the initial template;
- invalid-face count across the atlas and every reconstruction;
- runtime;
- neighboring-atlas, objective, and residual agreement for integration time
  points.

These metrics are complementary proxies. Nearest-vertex distance is not the
configured current/varifold objective, regularity magnitude is not physical
energy, and surface-area change alone cannot establish anatomical
correspondence.

## Remaining qualification work

- automate full-cohort selected-versus-neighbor confirmation;
- add PCA subspace and subject-score stability with sign/rotation-invariant
  comparisons;
- support predeclared biological strata in pilot selection;
- use independent homologous landmarks as target-registration-error evidence
  when available;
- validate thresholds on synthetic surfaces with known deformations and on
  independently annotated real cohorts;
- test initialization/template sensitivity and publish the complete benchmark.

The software and methods paper must report failures and ambiguous results, not
only successful calibration examples.

## Primary technical basis

- Bône et al., *Deformetrica 4: an open-source software for statistical shape
  analysis* — atlas objective, attachment/regularity trade-off, and LDDMM
  parameterization: <https://inria.hal.science/hal-01874752/document>
- Official Deformetrica registration tutorial — deformation kernel width as the
  characteristic deformation scale and noise standard deviation as the
  attachment/regularity control:
  <https://gitlab.com/icm-institute/aramislab/deformetrica/-/wikis/2_tutorials/2.1_registration>
- Official Deformetrica user manual — time points and initial control-point
  spacing conventions:
  <https://gitlab.com/icm-institute/aramislab/deformetrica/-/wikis/3_user_manual/3.2_model_xml_file>

These sources establish what the Deformetrica parameters mean. They do not
provide universal dataset-independent optimal values; the DiffeoForge search
and evidence thresholds therefore remain explicit methods that require
prospective validation.
