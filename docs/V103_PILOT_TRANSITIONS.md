# v103 — preserve approved pilot fits between stages

A good joint first-stage reconstruction could disappear from later comparisons.
Ordinary studies restarted from the original template, without learned fields,
and the deformation grid changed control spacing even at the selected kernel
width. None of those trials was an exact unchanged baseline.

v103 carries the selected estimated template into subsequent stages for ordinary
and adaptive studies. Unchanged deformation width and control spacing retain the
ordered learned controls and momenta. A changed spacing regenerates controls;
an incompatible deformation basis does not reuse the old momentum tensor.
Stage 4 still compares temporal integration and requires its numerical evidence
and explicit anatomical review. Final full-cohort configuration uses selected
geometry and controls, never a pilot-only momentum tensor.

## Keep an already approved reconstruction

Stages 2 and 3 include **Keep previously approved fit**. This is an exact reference
to the preceding selected output, with all five scientific settings retained.
No optimization or new visual approval is invented. The source manifest,
cohort, selected/completed events, run receipts, metrics, configuration and
latest visual decision must still match. Withdrawal or a new explicit rejection
blocks reuse. The original manifest, trial files and results are not rewritten.

The separate **Keep approved stage N fit → stage N+2** action can advance before
running alternatives, or after a completed unsuccessful comparison. It remains
disabled during a running task. Older saved stages can add this evidence reference
on explicit selection, avoiding a restart of individual fitting or repeated QC.
The action prepares the next stage; it does not start its calculations. Stage 4
cannot be skipped with this action.

Keeping a setting is a researcher decision to retain an approved fit, not evidence
that unexplored alternatives are worse, a search is bounded, or the morphospace
has been scientifically validated. New reconstructions still require visual QC.
Existing parameter grids are preserved; the fix does not promise a successful
fit for every dataset or silently select a baseline on reopening.

## Verification

Tests cover exact retained settings/output/approval, no optimizer dispatch,
old completed-stage recovery without trial edits, evidence tampering, approval
withdrawal and a new rejection, compatible/incompatible seed initialization,
desktop action visibility, retained-stage completion and export without pilot
fields. Scoped study, adaptive-search, sequence, dialog and build-identity checks
passed: 67 cases in the initial 70-case run, followed by 16 passing cases covering
the three corrected failures, retention regression paths and build identity.
These sets overlap. Ruff and compilation checks passed. No private scientific run or parameter
tuning is part of this software correction.

Independent first-use review and prospective anatomical acceptance remain open.
Installer build and local delivery evidence are recorded separately. Drive
distribution remains request-only.
