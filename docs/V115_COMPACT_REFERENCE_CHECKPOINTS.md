# v115 — compact reference checkpoints

New reference preparations and immutable resume successors default to
`output.checkpoint_mode: compact_final_export` (backend contract 0.5).
The protected run-local Python adapter uses the existing reference interpreter;
the installed Deformetrica environment is unchanged. Legacy saved evidence is
read without rewriting it. An explicit `native_full_outputs` schedule remains
available for comparison.

During optimization, the configured save cadence serializes the native optimizer
state without shooting and exporting every subject's complete mesh trajectory.
State replacement uses a temporary file, synchronization and atomic rename, so
a failed serialization leaves the preceding checkpoint intact. After the native
optimizer returns normally, the adapter saves a checkpoint before calling the
unchanged final output writer once. All retained flows, final reconstructions,
estimated template, controls, momenta and residuals remain available after a
successful export. Export progress reports completed subjects.

Neither attachment, gradients, optimization steps, convergence criteria,
integration, timepoint count, geometry nor anatomical decisions are changed.
The final export can still be expensive and requires the existing storage reserve.
Interrupted runs may contain only checkpoints; final mesh outputs are not promised
until export completes. A failed final export retains a resumable state.

Resume continues through a new hash-bound successor, including migration of a
legacy interrupted run to the compact output schedule. Source inputs, checkpoint,
manifest, inventory, results and decisions are preserved. Native Deformetrica 4.3
restores parameters and iteration but reinitializes objective baseline, gradient
and line-search state; resume is not an identical optimizer trajectory guarantee.

Verification includes failed checkpoint replacement, final-export failure,
GradientAscent output scheduling, plan/manifest protection, launcher,
resume and production-readiness regressions. A real reference-runtime synthetic
comparison produced exactly equal learned arrays and byte-identical final VTKs
with the original and compact schedules. Four compact periodic saves performed
no mesh export; one final export retained the same nine VTKs. A synthetic resume
restored iteration 4 and completed iteration 5. These are engineering checks,
not scientific validation or a completion-time guarantee for a private cohort.

The pending v114 desktop responsiveness correction is included in v115.
