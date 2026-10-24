# Protected regional pilot trials

The pilot can now translate marked original-surface feedback into an explicit
local fitting objective. This is a scientific change, beyond the v160 use of
marks only to measure saved fits and choose global parameter contrasts.

The user keeps one preferred comparison, can mark multiple problem areas, and can
also mark parts whose shape should be preserved while moving or areas to keep in
place. Source-bound spheres and 3D boxes survive saved feedback, reopening and
successor preparation. Individual areas can be removed without clearing all
marks. The symptom selector distinguishes missing detail, missed surface,
thickness, position, curvature, spacing, distortion and input/display problems.
Alignment, topology and display concerns lead to their relevant checks instead
of silently trying to correct them with another deformation.

## What is actually fitted

A regional trial retains the complete original target and the global surface
term. It adds a local Varifold surface term and sampled retained-position
constraints outside the active region and its declared transition halo. When
spacing/position or explicit shape preservation is requested, independent
connected patches are matched geometrically. Only approximately congruent,
translation-like parts receive common-movement point guides; incompatible parts
fail preparation with an explanation rather than receiving invented anatomical
correspondences. The common movement preserves relative positions within each
guide patch. Biological owner landmarks are not used in these objectives.

The first capture stage and stronger transition-balancing stage have distinct
local surface noise scales. Feedback and measured local/outside/shape response
determine whether an unfinished intermediate field can be a numerical seed.
This never promotes it to the human-preferred comparison. A Worse veto keeps
the earlier field. Subsequent contrasts remain available; there is no cumulative
trial budget or once-per-parameter lock. Changed areas, methods and symptoms
start separate recipe histories.

Mixed feedback remains separate: a spacing region may receive movement guides
while a curvature/thickness region receives shape matching. A shape error is not
forced into a shape-preserving guide merely because another marked area has a
spacing problem. Fixed-only marks require a problem area before a trial is prepared.

Local shape errors start from the retained endpoint with a smaller-scale residual;
spacing can first use a compatible retained original-source field. Residuals use
new, declared controls and zero initial residual
momenta. Old momenta are never reinterpreted under a different kernel. The saved
prefix remains unchanged. Evaluation replays the entire ambient field chain
forward from the original source, in Float64; interpolating a deformed endpoint
is not used as a substitute for that composition. The current implementation
retains the supplied source connectivity; automatic source subdivision is not
part of this delivery.

An ordinary global alternative cannot reinterpret only the last residual field
on the original template. It receives an explicit fresh initialization instead;
protected refinement retains the full prefix. The retained comparison stays saved.

All objective geometry, source/target identities, initial fields, controls,
recipe and derived guide files are hash-bound and staged with the run. The native
installation is unchanged. A run-local SciPy message compatibility wrapper only
normalizes the return-message type; it does not change an equation, gradient,
line search or optimizer step.

## Verification and user decisions

The measured, displayed and subsequently compared reconstruction is the same
bound full-source endpoint. Fixed-field evaluation compares 37/73 timepoints
and increases to 145/289 if the declared vertex-sensitivity bound is exceeded.
These are evaluations, not additional optimizations. Both directions of local
surface error, transitions, retained-position displacement, rigid-invariant
patch shape, and new self-intersection flags are checked separately. Failed
guards prevent automatic promotion; they do not create an anatomical decision.
Finite surface/patch checks are not a complete space-time diffeomorphism,
cross-section, feature-correspondence or homology proof.

Preparation and Run remain separate user actions. Long work stays in workers;
selectors use prepared data. The UI reports fitting plus post-check wall time
separately from native fitting time and labels fixed-field evaluation progress.
Trials and earlier preferences remain available after rejection or stagnation.
New marks trigger at most eight recent historical geometry comparisons (at most
two per family), retaining all older decisions and fits for explicit inspection.

Regional constraints are specimen-specific and define an extended objective.
They cannot silently count as approval of the old common atlas objective, pass
through the joint gate after being discarded, or donate separately fitted
momenta to the old PCA. The UI preserves and permits refinement of such results,
and states that a shared cohort protocol still needs separate qualification.

## Actual native qualification

Three controlled spacing errors on one real base surface were dispatched through
DF's real configuration, protected staging, supervisor and native backend. Their
capture and balancing stages reproduced all six Codex momenta arrays bit for bit.
Full-source Float64 73-point endpoints differed by less than 5e-16 model units.
Independent material-section checks were recomputed: all 16 tested sections per
case passed the predeclared 1% area/perimeter/diameter/width and 0.5% rigid-shape
limits. The endpoint results therefore reproduce the earlier approximately 99%
spacing-error reductions with under-1% tested width changes.

An additional real DF residual dispatch verified prefix retention, smaller-kernel
execution and original-source forward composition, with preserved outside shape.
These runs reached their iteration caps, not native tolerance. Software tests
also exercise actual pilot successor preparation, immutable asset staging,
regional guards, mark persistence and Qt controls. Native reproduction and
software routing are distinct evidence.

This establishes implementation parity for the controlled translation-like
spacing cases, not prospective anatomical validation across independent animals,
an isolated wall-thickness guarantee, or automatic reproduction of the earlier
three-field real-anatomy search. Mesh density, topology, severe compression,
correspondence and template suitability still require appropriate checks and
the researcher's visual decisions.
