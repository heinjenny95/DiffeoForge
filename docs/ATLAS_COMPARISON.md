# Quantitative atlas comparison

Status: **implemented for verified Modern Engine and Deformetrica results**

Compare Modern versus Deformetrica, balanced versus global, Euclidean versus Sobolev,
or two Width settings without relying on side-by-side PCA screenshots:

```powershell
diffeoforge atlas-compare C:\path\to\first-run C:\path\to\second-run `
  --first-label "Modern Sobolev" `
  --second-label "Deformetrica more-local" `
  --output C:\path\to\comparison
diffeoforge atlas-compare-verify C:\path\to\comparison
```

Both complete sources are independently verified. The immutable comparison contains:

- optimizer completion/convergence and runtime evidence for each run;
- separate residual median, p95, and maximum summaries;
- paired per-subject residual wins when specimen identities match;
- Jaccard overlap of the upper 10% residual inspection priorities;
- corresponding-vertex template RMS, p95, and maximum displacement when topology matches;
- paired sign/rotation-invariant PCA CKA and score-distance rank correlation;
- a tidy subject-residual CSV plus machine-readable and human HTML reports.

Cross-engine attachment-objective scales are never assumed equivalent. If topology or
subject identity differs, the corresponding paired metric is marked unavailable rather
than coerced. The report selects no automatic winner: lower residual, smoother template,
faster runtime, and stable PCA can represent different tradeoffs and remain separate.

