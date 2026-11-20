# Automatic neighboring-parameter sensitivity assessment

Status: **implemented for completed Deformetrica Validation Lab studies**

This assessment reuses the completed full-training finalist runs from Validation Lab. It
does not start or resume an atlas. The source study remains unchanged; DiffeoForge writes
an immutable sibling artifact instead.

```powershell
diffeoforge reference-sensitivity-assess C:\path\to\validation-study
diffeoforge reference-sensitivity-verify C:\path\to\validation-study-sensitivity
```

The assessment exactly recomputes four questions on the common frozen training cohort:

- estimated-template stability from ordered-vertex RMS, p95, and maximum displacement;
- overlap of the upper 10% surface-residual inspection priorities using Jaccard overlap;
- paired momenta-PCA stability using rotation/sign-invariant linear CKA and
  score-distance rank correlation;
- whether the Validation Lab preferred Width/spacing values lie at a tested boundary.

Control-point identity is hash-bound. Direct PCA feature-subspace angles are withheld
when the control-point files differ, while paired subject-score evidence remains valid.
Every run manifest, result, output inventory, atlas, momenta file, control-point file,
Validation Lab ledger, and report is bound into the assessment.

## Default engineering gates

- template p95 no larger than Validation Lab's declared practical geometric margin;
- high-residual-subject Jaccard overlap at least `0.50`;
- PCA linear CKA and distance-rank correlation both at least `0.95` at a `0.90`
  cumulative-variance target;
- a preferred parameter on the tested minimum or maximum triggers a search-extension
  warning even when the pairwise metrics are stable.

These are explicit numerical engineering gates, not biological effect-size thresholds,
taxonomic evidence, or automatic exclusion rules. CLI flags can change the gates, and
the chosen values are stored in the artifact so a changed threshold produces a new
assessment rather than silently changing an old decision.

## Scientific report integration

Attach both the parent study and the automatic assessment:

```powershell
diffeoforge scientific-report C:\path\to\atlas-run `
  --validation-study C:\path\to\validation-study `
  --sensitivity-assessment C:\path\to\validation-study-sensitivity
```

The scientific report marks neighboring-parameter robustness as supported only when the
parent study has a robust preference, the final atlas matches it, and the automatic
assessment is stable without a tested-boundary warning. Otherwise the report retains the
evidence but labels the claim partial.

