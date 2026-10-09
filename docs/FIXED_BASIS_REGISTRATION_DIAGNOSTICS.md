# Bounded fixed-basis registration diagnostics

When whole-specimen anatomy is rejected after atlas estimation, first separate
registration diagnosis from a new shared-template atlas. Preserve the completed
run, its analysis and human review. A native tolerance stop is not anatomical
acceptance.

## Bind the comparison before execution

Copy and hash-verify the completed atlas's estimated template, control points,
selected aligned targets and exact ordered momentum rows. Include a rejected
case and a comparison case explicitly approved by the researcher. Record the
source manifests, finalized QC binding, optimizer settings, runtime and copied
artifact hashes in a prospective diagnostic plan. Do not rerun alignment or
substitute display proxies for the scientific surfaces.

If an accepted pilot reconstruction exists, compare it with the current atlas
using identical original inputs and one distance definition. Do not compare
pilot point-to-triangle distances directly with the desktop's nearest-vertex
screening values. A sampled distance measures geometry, not anatomical
correspondence or a percentage of biological accuracy.

## Distinguish the questions

Freeze both template and control points and declare finite candidates before
observing their results. A useful bounded comparison can distinguish:

- Further optimization initialized from the completed atlas's own momentum row,
  with unchanged attachment and deformation settings.
- A zero-field initialization on the same fixed basis and with the same budget,
  to assess sensitivity to starting state.
- One explicitly changed matching weight, using the same starting field and
  optimization criterion as its baseline. For the same attachment model,
  halving noise standard deviation multiplies the attachment coefficient by four.

Any tighter optimizer tolerance is a separately declared diagnostic setting.
Record native tolerance, iteration cap and line-search stops separately. An
iteration cap does not demonstrate convergence; a lower objective under another
noise weight does not establish a better fit. Do not automatically expand the
candidate grid or convert numerical improvement into human approval.

Warm initialization requires matching template, control locations, deformation
kernel and subject order. An older pilot field on another learned basis must not
be transferred directly to the final atlas's basis. Initialization from saved
parameters also does not reproduce the native checkpoint's optimizer history.

For isolated one-subject runs, Deformetrica 4.3's momentum reader can squeeze the
subject dimension. Use the existing run-local
`reference_singleton_compat.SITECUSTOMIZE` adapter; it restores only that axis and
preserves all values. Keep any failed launch evidence and create a separate
corrected attempt rather than rewriting it.

## Output, verification and decision

An explicitly declared endpoint-only output policy may omit intermediate mesh
trajectory files. Keep native integration, likelihood, gradients and optimization
unchanged, and retain reconstructed endpoints, parameter arrays, compact
checkpoints and complete native stop logs. This output policy does not reduce
the number of integration time points.

Verify the fixed control coordinates and template geometry after every run.
Measure all candidates with the same full-resolution surface-distance method;
provide original/reconstruction overlays with a common camera and scale and
label any display-only simplification. Check that protected source evidence is
unchanged.

The resulting fits are conditional, in-sample diagnostics. They do not repair an
existing common atlas/PCA, establish generalization, or authorize exclusions.
Require anatomical review before selecting settings or starting a successor.
Any common successor needs consistent cohort/model provenance and early review
of the identified concerns; separately tuned fields must not be inserted into
the old PCA and presented as its original result.

## Refine a saved atlas on its existing basis

After the researcher selects diagnostic starting fields, a source-level
preparation may declare `preserved_atlas_momenta_fixed_basis_refinement`.
Bind the complete ordered starting tensor to the source atlas, recording any
reviewed replacement rows as initialization only. Freeze template and control
points and keep the shared attachment/deformation settings unchanged.

This mode sends all existing rows directly into one common native optimizer;
it skips the pilot workflow's per-subject initialization fits. It retains the
existing checkpoint-bound early review and prevents continuation until that
review is recorded for every declared inspection case. Fresh preparation cannot
reuse an old review or resume phase. The subsequent common outputs need new
cohort QC and a new PCA bundle. The current desktop has no dedicated preparation
button for this mode; a helper can prepare and supervise the run. Production
output still retains the complete final flows once, with compact checkpoints
during optimization. Diagnostic endpoint-only output is not a production import.

Verification: scoped configuration/checkpoint/review tests passed. A native
two-subject nonzero-seed check reached its declared early checkpoint without
individual initializer logs or a complete-flow export. This checks execution
and review gating, not anatomical validity of a subsequent cohort refinement.
