# Multi-start template robustness study

Status: **implemented for Deformetrica reference atlases; execution is explicit**

DiffeoForge can freeze a controlled multi-start study in which the subject cohort,
model, optimizer, and scientific parameters stay fixed while only the initial template
geometry changes.

```powershell
diffeoforge reference-template-robustness-init C:\path\to\atlas.yaml `
  --output C:\path\to\template-robustness `
  --starts 3
diffeoforge reference-template-robustness-status C:\path\to\template-robustness
diffeoforge reference-template-robustness-run C:\path\to\template-robustness
```

Initialization does not start an atlas. It copies or hard-links the immutable subject
cohort, retains the configured template as the baseline, and chooses up to three
additional subject-derived starts by deterministic maximin sampling in a robust geometry
descriptor space. A subject used as a start remains in the common subject cohort, so the
intended experimental difference is initialization only.

The runner executes one arm at a time, records a hash-chained event ledger, resumes
missing or interrupted arms, and never overwrites a completed attempt. Final assessment
reverifies all reference runs and compares:

- corresponding-vertex template RMS and p95 displacement;
- sign- and rotation-invariant momenta-PCA structure;
- overlap of upper-tail residual inspection priorities;
- explicit convergence and invalid-face gates.

The default template p95 gate is 0.5% of the configured template diagonal and the PCA
gate is 0.95 for both linear CKA and score-distance rank correlation. These are frozen
numerical engineering gates, not biological effect thresholds. A stable result supports
only robustness across the tested starts; it does not prove global optimality or replace
a bootstrap-cohort experiment.

Attach a completed study to the scientific report with:

```powershell
diffeoforge scientific-report C:\path\to\atlas-run `
  --template-robustness C:\path\to\template-robustness
```

