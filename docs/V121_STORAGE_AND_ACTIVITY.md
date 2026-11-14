# v121 — Complete export storage checks and quieter live feedback

Desktop reference runs below the production subject threshold previously bypassed
storage blockers. A smaller cohort with large surfaces and many retained trajectory
timepoints could therefore start without space for its final export or an immutable
continuation. Resume launch and the preparation worker repeated the same bypass.

Every desktop reference cohort now checks staged inputs, complete final mesh/flow
output, continuation space and the existing free-space reserve. New-run and resume
guards stop before preparation when the estimate does not fit. Production-only
checkpoint cadence remains production-only; scientific settings are not changed to
make a job fit. Review shows available and required storage for small cohorts too.

Planning uses the larger of observed source bytes and an ASCII coordinate/connectivity
estimate from mesh point/triangle counts, with the existing serialization safety
factor. This avoids treating compressed binary input size as final ASCII output size.
Resume planning also retains a larger observed output size. These are engineering
planning estimates, not guaranteed peak usage; available space can change after launch.

Ordinary activity reminders now use a 180-second interval. Resource sampling retains
its independent 30-second interval, and a schema-checked resource-only worker event
updates the desktop without appending another activity reminder or resetting the
current iteration display. Actual optimizer output, phase changes, cancellation and
terminal events retain their immediate paths. Older activity payloads remain readable.

Regressions cover sub-threshold large-mesh cohorts, binary-to-ASCII planning, new/resume
storage, rejection before preparation, separate resource/reminder timing, protocol
phase guards and resource-only UI updates. No private scientific computation or
anatomical decision is performed by these changes. The separately deployed server
runtime and its protected inputs remain independent of local source and installation.
