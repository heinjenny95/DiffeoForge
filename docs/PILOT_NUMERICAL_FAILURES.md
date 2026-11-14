# Explain a terminal numerical pilot failure

A guarded regional trial can stop with
`inconsistent_FG_for_identical_parameters`: the same exact parameter vector has
produced a different objective or different gradient bits. This is separate from
an iteration limit, inadequate surface fit or an anatomical decision. More
iterations do not resolve an inconsistent evaluation path. A generic return code
alone does not explain this distinction.

The source follow-up reads the protected manifest, matching terminal shutdown,
result-bound inventory and sealed guard violation/event metadata. It shows the
specific failure in the worker and pilot, including when an earlier failed study
is reopened. It disables rerunning that same terminal trial in the guided view
and blocks the launch request before a new attempt/event/controller is created.
Changed failure evidence also blocks dispatch pending review. Failed coefficients
are not read or restored; the retained earlier fit remains inspectable. Existing
qualified routes to prepare a different trial retain their separate requirements.

The numerical guard, comparison policy, objective, gradients, iteration cap and
precision are unchanged. Failure guidance replaces stale advice to optimize the
same failed trial longer. An unknown consistency cause stays unknown; do not
silently attribute it to GPU rounding, bad input geometry or insufficient effort.

The original source follow-up's 72 focused checks cover metadata, tampering, dispatch
prevention, worker errors, Qt views and existing guided/recovery behavior; targeted
lint passes. These are source checks. The last verified installed runtime remains
dev165 / `9b09531` until a separately verified delivery supersedes it. No owner
fit was restarted, no failure was relabelled successful and no new numerical
repair is claimed by that error-handling change alone. The subsequent dev166
[root-cause repair](PILOT_GRADIENT_REPEATABILITY.md) addresses the qualified legacy
CPU indexing problem; it preserves this strict failure policy.
