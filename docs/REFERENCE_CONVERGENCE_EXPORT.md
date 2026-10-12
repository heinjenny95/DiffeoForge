# Export only after native tolerance convergence

An explicitly authorized precision successor can use
`prepare_resume_run(precision="float64", convergence_reference=...)` to promote
the actual reference model arithmetic from float32. The tolerance and native
strict stopping comparison stay unchanged. At large objective magnitudes,
float32 spacing can exceed the tolerance-scaled accumulated improvement, making
every strictly positive accepted step too coarse to meet that comparison at the
current values. Converting an already rounded scalar to double does not fix this;
the model, attachment, regularity and gradients must be evaluated in float64.

The immutable successor records the explicit precision change in effective
config, model XML and protected resume provenance. All source checkpoint bytes,
geometry, weights, integration and original evidence are retained. Native tensor
conversion promotes saved parameter values for model evaluation. A fresh
reference evaluated at its declared checkpoint in float64 is required; an
inherited reference from the earlier arithmetic cannot be silently reused.
Following capped successors inherit both float64 and the matching reference.
Defaults do not change, and precision downgrades are not supported by this API.
Precision promotion changes the numerical calculation and does not promise an
identical trajectory, convergence time, anatomical validity or a global optimum.

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
likelihoods, gradients, line search, integration and tolerance equations are
retained. Ordinary resume reinitializes the native objective baseline, gradient
and line-search state. Capped checkpoints are support evidence, not a completed
shape delivery.

An explicitly supplied `prepare_resume_run(convergence_reference=...)` can retain
the original full-precision objective reference across convergence-only capped
successors. This opt-in reference has a version, origin iteration/checkpoint
hash, objective value and unchanged tolerance. The caller must obtain it from
the same native model/runtime at the declared immutable origin; rounded logs are
insufficient. The protected resume provenance and generated adapter bind it.
Following successors inherit it and require the matching checkpoint context;
they cannot silently reset or replace it. Defaults and historical runs retain
their previous semantics.

The adapter verifies the audited native update's source hash, then adapts only
its two initial objective assignments. The convergence reference persists, while
the first line search compares against the resumed current objective. The native
stopping comparator, scalar precision and log message are retained. The context
travels atomically with the parameters and iteration in the same checkpoint.
Unsupported native code, missing inherited context, conflicting references,
nonfinite values or a tolerance mismatch fail closed before an optimizer step.
Gradient and step sizes still reinitialize, so this does not claim an identical
uninterrupted trajectory, guaranteed convergence or anatomical approval.

The logging observer is attached only during the original native update and
removed even on exceptions. A tolerance string from another logger or outside
that update cannot enable export. The latest checkpoint is saved before either
deferring output or invoking the original complete writer. Existing atomic-save
and export-failure protection remains in place.

Preserved-pilot initialization and saved-atlas refinement accept both compact
schedules through the same output-mode predicate. The earlier equality check
against only the default schedule rejected an otherwise valid convergence-only
successor before its backend started. The compatibility fix keeps the frozen
basis and checkpoint-bound review requirements. Regression checks cover the
reviewed early endpoint, ordinary capped continuation, output-policy transition,
another checkpoint-only successor and the composed atlas/export adapters.

An active run is never edited to switch policy. A separately identified successor
is prepared only at a verified block boundary. Any operational driver handoff
must distinguish its planned guard stop from a failed or interrupted backend;
this output option does not authorize automatic error recovery or anatomical QC.

Verification: 108 scoped public regressions cover scheduling, protected
preparation, reference continuity and validation, checkpoint-only chaining,
source preservation, backend configuration, atlas initialization and terminal
reports. Controlled-objective tests show the preserved reference reaches the
same stopping criterion across a cap and rejects a worsening first resumed
step. The composed adapter imports in the installed native Python 3.8 runtime;
controlled scalars exercise that runtime's original update, class closure,
native precision, tolerance/line-search messages and atomic context bundle.
Float64 controlled native scalars resolve a strictly positive step below the
unchanged tolerance threshold, while the same values collapse in float32.
These engineering checks do not optimize private meshes.
