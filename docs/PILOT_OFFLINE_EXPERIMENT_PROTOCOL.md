# Offline pilot-method qualification protocol

This is a research protocol for an owner-authorized, isolated template-target
registration experiment. It is not a production pilot implementation or a
cohort-level qualification. Private inputs, configurations, native outputs,
measurements and images remain with the owner's dataset.

## Preserve the reference and establish numerical consistency

Freeze and hash the original template, target, retained initial control points
and fitted momenta. Re-evaluate that field without optimizer updates on the full
original template before attributing any change to parameter selection. Check
time-grid sensitivity separately from optimization. Record the complete native
configuration, runtime versions, source identities, termination and elapsed time.

Mesh validity and matching topology are separate checks. Closed, connected,
two-manifold surfaces can still have different genus. A diffeomorphic deformation
preserves this distinction; it does not establish which specimen's segmentation
is anatomically correct. Never repair topology or change the cohort implicitly.

## Separate numerical adequacy from parameter hypotheses

Include an unchanged-physical-parameter optimization control. A native tolerance
message describes that solver's stopping test, not a global minimum or sufficient
registration. Retain iteration caps, abnormal line searches and interface failures
as distinct outcomes. A failed predecessor without an exported, bound field must
not seed a dependent run.

Compare a small number of explained attachment, scale, weighting or basis
hypotheses. Compatible trials may retain the existing field. A change of deformation
metric or basis requires a verified transfer or an explicitly separate restart;
copying parameter labels does not preserve the learned deformation.

## Qualify explicit working geometry, then return to full originals

An optimization-only source approximation must be declared, immutable and checked
against the complete source in both directions, including dense vertices and
area samples. Such observed distances are not certified Hausdorff bounds.

For fixed template/control-point registration, the learned ambient field can be
evaluated on the original full template. Measure and display that reconstruction,
not the simplified working mesh. An approximate objective is a screening aid;
finalists still require full-objective verification or refinement and numerical
resolution checks. Do not infer a speedup attributable to simplification from a
comparison that also changes optimizer, iteration count or stopping criteria.

## Measure geometry independently of the fitted objective

Use area-based point-to-triangle measurements in both directions. Report global
mean and tails, the same fixed original marked patches, and unmarked target
regions separately. Repeat deterministic sampling to expose sampling sensitivity;
two repetitions do not constitute a statistical confidence interval.

Keep two preservation questions distinct: whether the unmarked surface changes,
and whether corresponding vertices of the retained template move. Tangential
movement can alter the latter greatly while changing the surface little. Neither
small surface error nor a retained vertex index proves biological homology.

Raw attachment objectives across methods, weights or working geometries cannot
rank reconstruction fidelity. Inspect fixed-camera full-resolution overlays and
marked-area close-ups. No measurement creates anatomical approval.

## Treat a protected local objective as a separate method

A prototype may combine a whole-surface term, an additional marked-patch surface
term and soft retained-position anchors outside a transition halo. The anchors
use known correspondences within one template and its retained reconstruction;
they are not newly annotated biological landmarks. This changes the objective,
not merely the next parameter suggestion.

Evaluate regional gains, outside-shape changes and outside-vertex movement
separately. Record patch selection, halo and term weights explicitly. Such
individual constraints must not silently redefine the common metric or the
statistical feature space of a cohort atlas/PCA. Independent anatomical assessment
and cohort-level validation remain necessary before product adoption.

Application source and installed behavior remain separate from private experiment
scripts. A successful single pair cannot establish a universally best search
policy, guarantee monotonic improvements or qualify the production pilot.
