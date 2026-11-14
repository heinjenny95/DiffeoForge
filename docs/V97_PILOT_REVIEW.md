# v97 — responsive pilot review and selected continuation

The pilot's numerical leader can have inadequate anatomy. A sampled distance is
not an anatomical percentage, and reaching the objective tolerance does not prove
surface fit. The review workflow must make this distinction visible without
requiring full-resolution rendering or an individual acceptance click per specimen.

## Behavior

- Completed options can be inspected while other options compute. Comparison
  preparation, input verification and display preparation run outside the GUI.
  Background prefetch prepares finished options for subsequent inspection.
- Pilot previews use bounded, versioned display geometry cached in the study's
  `display-cache` directory. Current source bytes are hashed before cache reuse.
  The common ASCII VTK path uses vectorized parsing and avoids constructing
  millions of unused wireframe edges. Other formats use the validated reader.
  Scientific inputs and engine geometry are unchanged.
- Preview inspection supports both rejection and approval. Original detail is
  an optional load for features that simplification may hide. After viewing all
  specimens, one explicit **Approve all specimens** action records
  their acceptance. Per-specimen concerns and anatomical checks remain optional;
  unresolved concerns block approval. Rejection is available after any specimen
  comparison is displayed. Loading, hidden layers and failed rendering cannot
  authorize a decision.
- Preview/original evidence scope is recorded. A separate atomic, hash-chained
  visual-review journal preserves decisions throughout successor studies without
  changing frozen engine event chains. Stage selections and reports retain scope.
  Legacy every-specimen decisions remain readable.
- Percentage quality labels are removed from candidate cards. Size-normalized
  nearest-vertex p95 remains technical evidence behind disclosure, with its units
  and limitations. The numerical leader is described as lowest measured distance,
  never as a verified anatomical winner.
  Relative speed/cost badges are folded into option details rather than presented
  as prominent evidence of anatomical quality.
- **Continue option** adds one successor fit with the selected learned template,
  control points and ordered momenta. The effective model and optimizer settings
  are preserved; only the explicitly chosen additional iteration budget changes.
  Optimizer step history restarts. Original runs remain intact. Iteration-limited
  options can be reviewed and continued but still require convergence and explicit
  anatomical acceptance before stage advancement. Numerical failures cannot seed
  this continuation. A new result requires its own review.
- Additional automatic search is optional and off by default. Existing recorded
  budgets remain immutable. Search excludes recorded anatomical failures and
  prioritizes researcher-approved centers over unreviewed distance leaders.
  Unreviewed candidates still require numerical comparison and human inspection.
- Ancestor snapshots are verified once within each read. No verification cache
  survives that read; fresh reads continue to detect changed source evidence.

## Limits and acceptance

This update improves responsiveness, evidence presentation and reuse of promising
results. It does not establish that the bounded search will find adequate fits for
every dataset, replace anatomical judgement with a better percentage, or make a
fixed iteration cap universally sufficient. Large scientific meshes can still
make the engine expensive. A common template and nonlinear optimization can
retain poor fits despite numerical completion. More iterations can help only when
optimization remains productive; they cannot guarantee recovery from a poor minimum.

Scope-specific regression tests cover preview reuse/corruption/source changes,
GUI responsiveness, preview bulk approval, persistent review scope, successor
lineage, selected cap-limited continuation, exact model preservation, feedback
selection and legacy study/report behavior. Synthetic UI and packaging checks are
separate from native first-use acceptance and prospective scientific fit validation.
No private pilot or full-cohort atlas is launched for this implementation.

110 distinct scoped regression cases passed across the affected batches, with
the final presentation checks rerun after shortening labels. Ruff and synthetic
themed review/pilot layout checks passed. This is not a full-suite or prospective
scientific-fit validation claim.
