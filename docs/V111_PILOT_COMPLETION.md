# v111 — separate final pilot evidence and explicit completion

A saved joint fit can have acceptable anatomy and integration yet reach its
optimizer iteration cap. Earlier versions combined those independent questions
with whole-continuation objective, geometry and velocity drift budgets. Repeated
strict continuation was consequently the default final action. Those engineering
budgets are not validated universal limits on morphospace accuracy.

## Final-stage behavior

- **Check time resolution (no optimization)** reuses a verified fixed-state
  check, or shoots the unchanged saved model on N, 2N−1 and 4N−3 time grids.
  The existing roundtrip and integration engineering tolerances still apply to
  every pilot subject. It never fits another atlas or changes the saved model.
- An unfinished historical optimizer check retains its original declaration and
  resumes under an explicitly different label. Optional strict continuation and
  finer-model refitting remain separate actions; neither approves anatomy.
- A recommendation requires native optimizer convergence under its recorded
  tolerance, complete valid joint geometry, verified fixed-state integration,
  and recorded anatomical acceptance of that exact result. No automatic
  selection follows. Whole-continuation drift remains visible diagnostic evidence.
- A complete valid joint result stopped only at its iteration cap can instead
  **finish provisionally**, after verified integration, recorded joint anatomical
  approval and explicit acknowledgement. It never becomes a converged
  recommendation. Rejected, incomplete, invalid or unchecked fits remain blocked.
- The latest completed, non-rejected saved result is preselected for inspection.
  Selection is not QC. Completion prepares a full-cohort configuration; it does
  not run or approve a full atlas.

## Provenance and compatibility

Original qualification receipts, failed gates, criteria and hashes are unchanged.
New checks bind their declaration, source manifest/configuration, geometry,
subject order, fixed-state outputs and receipt hashes. Reopening and finishing
verify that evidence and the exact recorded researcher decision. JSON/HTML
reports, audit export and configuration disclose provisional/nonconverged status
and the original receipt's decision. An old failed receipt is never displayed as
passed merely because the new completion policy allows proceeding.

The full-cohort configuration retains the learned joint template and common
control points, starts new full-cohort momenta at zero, and restores the original
project's declared optimizer convergence tolerance. A stricter diagnostic
criterion is not silently inherited. Both tolerances and their origin are recorded.
No independently fitted subject momenta are spliced into a shared morphospace.

## Acceptance and limitations

Scoped regression checks cover no-optimization dispatch, immutable cached reuse,
all-subject integration failure, fresh approval, rejected anatomy, explicit
provisional acknowledgement, artifact tampering, legacy failed-receipt meaning,
original full-cohort tolerance, schema/configuration, report/audit and reopening.
A saved pilot was opened read-only without starting a scientific run or changing
its recorded decisions. Build/install evidence is documented separately.

This change permits a disclosed research decision; it does not establish
optimizer stability for capped results, a global optimum, stable momenta or
biological validity. Integration thresholds are engineering checks, not bounds
on morphospace accuracy. The new full-cohort atlas still requires reconstruction
and anatomical QC. Native owner acceptance and prospective scientific validation
remain open.
