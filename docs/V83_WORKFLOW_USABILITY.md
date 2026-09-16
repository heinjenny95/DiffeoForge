# v83: clearer workflow and responsive activity feedback

This is a development candidate, not a scientific qualification or public release.
No private analysis was rerun, no existing project was converted and the
researcher's installed application was not changed while developing this package.

## Changes

- New GUI projects select Deformetrica Reference. Modern remains explicitly
  experimental and opt-in; its technical pilot is distinguished from calibration.
  Saved configuration routing and programmatic request defaults are unchanged.
- The project-created card shows the engine, subject count, next action and
  actionable warnings. Paths, provenance and routine notices start collapsed.
  Comparison summaries distinguish numerical method checks from registration or
  biological validation; unsuccessful checks remain visible warnings.
- Actual worker and preview-loader signals drive a window-scoped busy cursor
  and short activity row. Overlapping jobs do not clear each other's state.
  Unknown-duration operations use an indeterminate indicator, not invented ETA.
  Pilot and Validation Lab have their own indicators. Cancellation remains busy
  until the underlying operation actually returns.
- QC collection releases each reconstruction after measuring it, rather than
  retaining every cohort mesh. Full-resolution geometry, source/inventory checks,
  metric version 0.2, sample order and quantile definitions are unchanged.
  Result reopening reports verification stages and actual completed-subject counts.
- AFK return summaries expose recorded uncertain recommendations, search-boundary
  limitations and sensitivity warnings alongside the existing selected values.
  They neither rerank choices nor create anatomical approval. Validation Lab is
  explicitly optional and describes nearby kernel/control-point tests with fixed
  noise; method-comparison help distinguishes feature-space variance definitions.

## Verification

- 110 targeted desktop/presentation tests passed; one deliberate optional-package
  test skipped because PySide6 is installed. Includes both engines, AFK/manual
  presentation, real threaded completion, overlapping tasks, cancellation and
  receiver destruction before completion. Repeated mixed Qt suites passed after
  removing ownership cycles from the new signal bindings.
- 93 scientific/regression tests passed across Reference PCA/comparison,
  calibration-study, Validation Lab and metric collection. An additional
  independent uniform-scale area-ratio test checks nonzero distortion; all six
  metric tests pass. Changed staged input still fails integrity verification.
- Public five-subject metric fixtures match the pre-streaming residual and
  sensitivity values to 1e-14 absolute tolerance. Weak-reference instrumentation
  observes at most three live full mesh objects during collection (initial
  template, current reconstruction and target), with none retained on return.
- Repository Ruff check passed. Offscreen screenshots confirm the fresh Reference
  selection and collapsed project card with warnings visible. This is not a
  substitute for native interactive acceptance with representative inputs.

## Limits and next acceptance

Aggregate distance/distortion arrays and hash verification still cost memory/time;
this is not a constant-total-memory or measured large-cohort speedup claim. Busy
feedback does not by itself move every synchronous action to a background worker.
The same runnable is protected against duplicate submission; existing action
guards remain responsible for avoiding distinct duplicate jobs. Numerical and
visual scientific decisions remain the researcher's responsibility.

Run candidate CI and frozen-runtime tests, then obtain native first-use review of
the complete Reference route. Installation, author review and public distribution
remain separate decisions. See [preprint gates](PREPRINT_READINESS.md).
