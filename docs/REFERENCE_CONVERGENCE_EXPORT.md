# Export only after native tolerance convergence

The opt-in `output.checkpoint_mode: compact_convergence_export` keeps the native
atomic checkpoint cadence but defers the full mesh/trajectory writer until
GradientAscent explicitly logs its tolerance stop. The default remains
`compact_final_export`, which exports at every normal terminal block.

A completed capped block in the opt-in mode is checkpoint-only: successful
process completion and a verified inventory do not imply complete reconstructed
shapes or convergence. An explicitly authorized continuation can use the same
canonical +300 successor preparation after verifying the sealed lifecycle,
return code, log, checkpoint size/hash and finite parameter arrays. Final
convergence still requires a successful complete export and full reconstruction,
integration-timepoint, size and hash verification. Line-search exhaustion,
unknown stops, interruptions and errors never authorize another block.

Resume can explicitly select the output mode; the protected successor config,
adapter and `resume.json` record that change. Source runs are preserved. Native
likelihoods, gradients, updates, line search, integration and tolerance equations
are not replaced. Resume still reinitializes the native objective baseline,
gradient and line-search state; a continuous uninterrupted trajectory is not
claimed. Capped checkpoints are support evidence, not a completed shape delivery.

The logging observer is attached only during the original native update and
removed even on exceptions. A tolerance string from another logger or outside
that update cannot enable export. The latest checkpoint is saved before either
deferring output or invoking the original complete writer. Existing atomic-save
and export-failure protection remains in place.

An active run is never edited to switch policy. A separately identified successor
is prepared only at a verified block boundary. Any operational driver handoff
must distinguish its planned guard stop from a failed or interrupted backend;
this output option does not authorize automatic error recovery or anatomical QC.

Verification: 92 scoped regressions cover scheduling, protected preparation,
checkpoint-only successor chaining, source preservation, backend configuration,
atlas initialization and terminal reports. The generated adapter also compiles
with the installed native Python 3.8 interpreter, and the observed stop messages
match that runtime's GradientAscent source. No private optimizer was run for
these engineering checks.
