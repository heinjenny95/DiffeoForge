# Scientific atlas completion report

Status: **implemented evidence-composition layer; biological review remains human**

The scientific atlas report is the publication-facing companion to the lower-level
terminal result report. It works for verified Deformetrica reference runs and verified
Modern Engine workflows. It does not rerun an atlas, alter its files, or silently turn
technical success into scientific validity.

## Create and verify a report

For a verified atlas/PCA result:

```powershell
diffeoforge scientific-report C:\path\to\atlas-run
diffeoforge scientific-report-verify C:\path\to\atlas-run-scientific-report
```

The default report directory is a sibling named `RUN-scientific-report`. This is
intentional: Modern workflow directories have an exact immutable inventory, so derived
reports must not be written into them.

Completed robustness evidence can be attached explicitly:

```powershell
diffeoforge scientific-report C:\path\to\atlas-run `
  --validation-study C:\path\to\diffeoforge-validation-lab `
  --holdout-study C:\path\to\heldout-confirmation `
  --pca-stability C:\path\to\pca-stability `
  --decision-review C:\path\to\registration-qc-review.json `
  --output C:\path\to\paper-atlas-report
```

The desktop Results & PCA page creates the same report with one button. It first records
the current Deformetrica registration-QC decisions as an immutable review when needed.
The initial desktop action does not guess which external Validation Lab or PCA-stability
artifact belongs to a run; those stronger bindings are explicit in the CLI.

## Output bundle

Every report directory contains:

- `scientific-report.html`: self-contained, script-free human review;
- `scientific-report.json`: complete machine-readable report payload;
- `methods.txt`: an editable paper-methods draft using the exact effective settings;
- `subject-qc.csv`: ranked subject residuals and recorded review decisions;
- `claim-matrix.csv`: supported, partial, unassessed, and unsupported claims;
- `user-decisions.csv`: the source-bound researcher decisions included in the report;
- `scientific-report-manifest.json` and its SHA-256 sidecar: exact output inventory and
  source-evidence bindings.

The HTML embeds verified optimizer and PCA SVGs when available and adds a deterministic
ranked-residual figure. It performs no network requests.

## Claim matrix

The report answers separate questions rather than returning one misleading green check:

- Was execution and artifact integrity verified?
- Did the optimizer's own convergence evidence pass?
- Were every subject reconstruction and explicit researcher decision reviewed?
- Was the chosen configuration tested against neighboring parameter values?
- Was a fixed trained template tested on heldout subjects?
- Was the PCA structure compared across paired analyses?
- Was dependence on the starting template or bootstrap cohort tested?
- Was independent anatomy-specific biological validation performed?

Each item has one of four states:

- `supported`: the attached verified evidence supports the narrow stated claim;
- `partial`: relevant evidence exists, but the complete claim is not established;
- `not_assessed`: no suitable verified evidence was attached;
- `not_supported`: the available evidence contradicts the claim, for example a Modern
  atlas that completed at the maximum cycle count without meeting its convergence rule.

## Subject flags are not exclusion decisions

When at least four subject residuals exist, DiffeoForge applies a deterministic robust
upper-tail rule (`Q3 + 1.5 × IQR`) only to prioritize visual inspection. The report keeps
the continuous residual, rank, threshold, and researcher decision separate. A flagged
specimen may be a biological extreme, an underfit registration, a damaged input, or a
combination; DiffeoForge never excludes it automatically.

Reference reports use the existing symmetric surface-reconstruction residual p95.
Modern reports use the final manifested subject residual. These metrics are named
explicitly and are not treated as sharing a scale across engines.

## Landmarks and downstream measurements

If Generalized Procrustes Analysis is enabled, the methods draft states that landmarks
were used only for pre-alignment. They are not described as an atlas attachment or as
independent validation evidence. Downstream helix-geometry or winding measurements are
likewise not promoted into atlas validation by this report.

## Evidence and immutability

Creation first reverifies the complete source atlas/PCA result. The report manifest then
binds both source manifests and every optional study/review artifact by path and SHA-256.
Verification rejects changed source evidence, changed report files, missing files,
additional files, symbolic paths, or a changed output inventory.

Reports are published atomically into a previously absent directory and are never
overwritten. A later scientific review therefore produces a new, distinguishable report
instead of rewriting prior evidence.

## Current boundary

The report composes evidence that already exists. It does not itself launch sensitivity,
multi-start template, bootstrap, or biological validation runs. Missing evidence stays
visible in the claim matrix. That separation prevents a convenient document generator
from becoming an undocumented scientific decision engine.
