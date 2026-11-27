# Post-PCA subject metadata

Status: **implemented for verified Deformetrica and Modern Engine PCA bundles**

DiffeoForge joins taxonomic, sex, body-size, locality, or other subject variables only
after the unsupervised atlas PCA has been verified. Metadata never enter atlas fitting,
surface attachment, or PCA-axis estimation.

```powershell
diffeoforge pca-metadata C:\path\to\pca-bundle C:\path\to\metadata.csv `
  --id-column subject `
  --output C:\path\to\pca-metadata
diffeoforge pca-metadata-verify C:\path\to\pca-metadata
```

The ID column must match every verified PCA subject label exactly and uniquely. This
fail-closed join prevents silent row shifts, filename truncation, or accidental mixing of
cohorts. Other fields may contain blank values.

DiffeoForge classifies fully numeric columns as continuous, low-cardinality text columns
as categorical, and high-cardinality text as identifiers. It exports:

- `joined-pca-metadata.csv`, a tidy score/metadata table for R or Python;
- `categorical-group-summary.csv`, group counts and per-PC mean/standard deviation;
- `continuous-pc-associations.csv`, complete-case Pearson and Spearman correlations;
- `pca-inspection-priorities.csv`, a robust upper-tail score-radius inspection aid;
- deterministic PC1–PC2 SVGs colored by every continuous or categorical variable;
- a human HTML report and machine-readable analysis with exact source hashes.

No automatic hypothesis-test p-values or cluster labels are produced. Group summaries,
correlations, and PCA-radius flags are descriptive. The radius rule prioritizes visual
inspection; it is not a biological outlier definition or exclusion decision.

