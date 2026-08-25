# DiffeoForge calibration evidence standard

## Claim boundary

DiffeoForge must never equate optimizer convergence with registration quality
or call one parameter set universally optimal. The strongest defensible claim
is dataset- and objective-specific:

> Within the predeclared search domain and validation criteria, DiffeoForge
> identified a Pareto-optimal parameter set whose preference was robust to
> reasonable metric priorities and predeclared cohort resampling. Untouched
> heldout and anatomy-specific evidence are reported as separate gates.

## Evidence levels

1. **Starter** — geometry-scaled values only; no executed registration evidence.
2. **Eligible** — completed and converged; no invalid atlas or reconstruction
   faces; all required metrics are finite.
3. **Sensitive** — an eligible Pareto winner exists but changes under reasonable
   metric weights, subject resampling, or independent rank aggregation.
4. **Robust pilot** — at least three eligible candidates; base winner has a
   score margin of at least 0.05, wins at least 75% of weight scenarios, agrees
   with weighted ranks, and wins at least 70% of subject bootstraps when those
   data are available. Automatic continuation additionally requires that the
   winner is interior to every searched attachment, deformation,
   control-spacing, and noise range.
5. **Validation-Lab robust** — frozen selected and neighboring finalists are
   compared on identical non-heldout cohorts with a parameter-independent
   vertex-to-triangle surface metric; the same finalist wins at least 80% of
   the predeclared full-training and resampling comparisons.
6. **Heldout supported** — training-only templates and control points are frozen;
   the same untouched subjects are registered against every finalist; and one
   finalist receives at least 80% paired subject support under the predeclared
   external metric and equivalence rule.
7. **Externally validated** — independent homologous landmarks, synthetic known
   deformations, replicated cohorts, or another task-relevant ground truth
   corroborates the chosen correspondence scale.

Level 5 supports only the explicitly scoped phrase "robust within the tested
finalist search space." Strong biological parameter-selection language
requires level 7. Level 4 permits automatic continuation but remains a pilot
result. A statistically robust winner at the minimum or maximum tested value
is recorded as `search range not bounded`, not as an enclosed optimum, and
automatic selection is withheld until outward evidence exists or a researcher
explicitly authorizes the boundary value as provisional.

## Current pilot metrics

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

- execute and publish the fixed-template holdout protocol on independent real
  datasets and calibrate its predeclared support thresholds prospectively;
- bind the implemented sign/rotation-invariant PCA subspace and subject-score
  stability primitives into a newly versioned Validation Lab protocol and
  calibrate its thresholds prospectively;
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

The implemented post-pilot protocol, confidence states, external metric, and
analytic known-correspondence generator are specified in
[DiffeoForge Validation Lab](VALIDATION_LAB.md).
