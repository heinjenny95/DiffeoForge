# v113 — preserve the aligned cohort when applying a learned pilot seed

The completed pilot may initialize the full atlas from its learned template and
control points. Previously, the subject glob excluded only the current template.
When the learned template lived outside the aligned input directory, the original
initial-template copy became an extra subject. The alignment review also compared
its preprocessing records with the learned template's filename instead of the
original aligned cohort template, blocking configuration review.

Input resolution now distinguishes the learned seed from the original cohort
template recorded in the calibration plan. Before excluding that original copy,
it verifies the original template, learned template and control-point hashes and
checks the declared full-cohort subject count. Alignment review uses the original
cohort identity and retains every existing raw/aligned mesh, landmark and scaling
evidence check. A short initialization row explains the learned seed. Ordinary
external templates and separately staged probes/holdouts retain their explicit
cohort behavior; no filename convention silently excludes a specimen.

Saved calibrated configurations and pilot journals need no rewriting or rerun.
Parameters, provisional warnings, anatomy decisions and numerical criteria remain
unchanged. The full atlas still requires an explicit user launch and later QC.

Sixty-four scoped regressions passed across two targeted groups (23 existing
config/review/adaptive cases and 41 handoff/version/completion/retention cases).
Ruff and diff checks passed. These regressions exercise broad-glob final export, the complete aligned
configuration review, unchanged source inputs, original/learned template and
control tampering, changed subjects and landmarks, extra/missing subjects, and an
ordinary external-template configuration. Existing completion, retained-stage,
config and review checks are run separately from packaging/installation evidence.
An existing completed owner cohort is also verified read-only. These checks do
not establish optimizer convergence or scientific validity.
