# v107 — retain a selected fit after reviewing several attempts

Keeping the preceding approved fit in stages 2/3 could fail with `Invalid
candidate visual review` when the same stage also contained reviews of another
option or an earlier continuation. The retention verifier supplied one candidate
to a review loader while passing the entire stage's review history. This could
also leave an older prepared stage without its retained baseline.

The verifier now selects the source candidate's reviews from the verified event
and review journals before validating their output bindings. Other options keep
their own decisions; every decision for the selected result remains in order,
including later withdrawal. No approval is created, evidence edited or optimizer
started. The existing **Keep approved stage N fit** action can recover a saved
stage with unsuccessful alternatives. A provisional source stays provisional;
Stage 4 convergence and numerical comparison requirements remain unchanged.

Verification: 41 scoped retention, provisional-selection, screen-dialog,
version and Windows-installer cases passed. Four new regression cases cover
other accepted/rejected alternatives with both converged and iteration-limited
sources, exact output preservation and a subsequent source-approval withdrawal.
The defect was reproduced before the correction; Ruff, compilation and diff
checks passed. A saved study's retention reference was validated read-only,
without registering a baseline, selecting a stage or running a private fit.
Packaging and local installation are recorded separately. Drive uploads remain
request-only. This correction does not establish scientific parameter adequacy.
