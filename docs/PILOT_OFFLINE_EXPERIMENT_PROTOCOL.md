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

An aggregate marked-region score can hide a missing small feature. Where the
dataset warrants it, inspect distinct feature caps, their coverage in both
directions, extent and position, and the complete feature group in solid views.
A cropped region may exclude a relevant branch. Geometry-derived endpoints or
branch assignments are diagnostics, not established biological homologies.
Endpoint constraints also need a surface-level control: matching the endpoint
does not establish a correct intervening shape.

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

A separately declared small-scale residual deformation may start from the
complete retained reconstruction with a zero field. Qualify this identity start
explicitly; it avoids copying momenta between different deformation kernels.
This is a composition with a new deformation metric and basis, not an ordinary
continuation under the original single metric. Keep broader capture and finer
surface matching as explicit stages, and retain an earlier result when a stage
regresses. Changes of region, protection, basis and objective remain visible.

Check temporal integration and spatial tessellation separately. A smooth ambient
map is represented by straight triangles in an exported mesh; their intersections
must not be dismissed because sampled Jacobians are positive. Conforming linear
subdivision before evaluating an unchanged field can test this representation
error without smoothing, target projection or changing the input surface.
Preserve old vertices, validate the identical input surface, edge incidence and
topology, and track parent faces for repeated regional measurements. Report
sampled Jacobians and full-triangle intersection tests with their limits.

For composed fields, evaluate every retained deformation on the original
reference vertices at declared precision. New vertices from conforming source
subdivision must traverse the complete composition. A rounded intermediate mesh
or linear interpolation of a deformed mesh is a different representation; do not
silently treat it as the original ambient composition. Check integration
sensitivity on the same source tessellation and retain exact field identities.

Unmarked regions are not necessarily already correct. Use bidirectional residual
maps to distinguish well-supported retained surface from missing structures and
overhangs before defining protection anchors. Record this confidence rule as a
new hypothesis, and check the previously good regions separately after fitting.
Good average preservation can coexist with a small local regression. Likewise,
a positive sampled determinant may still indicate severe compression; neither
it nor a zero endpoint-mesh intersection count establishes anatomical homology,
trajectory-wide validity or suitability for morphometric statistics.

Application source and installed behavior remain separate from private experiment
scripts. A successful single pair cannot establish a universally best search
policy, guarantee monotonic improvements or qualify the production pilot.

## Qualify feedback-to-action rules before implementing them

A visible symptom is not a uniquely identified parameter fault. Test proposed
responses against saved reconstructions with a declared hypothesis and regional
success/failure criteria. Separate historical replay, prospective matched
contrasts and adaptively selected follow-ups; known historical outcomes are not
an independent validation set. Multiple fits of one specimen remain one specimen.

For a parameter contrast, bind the same initial field, source, target, protection,
control basis, optimizer and configured iteration budget. Inspect the actual
native XML to verify only the intended parameter differs. A matching-kernel
change can also alter objective scale; an unchanged noise setting does not prove
normalized equal fitting strength across kernels. Evaluate both continuations
on the same complete original-reference surface and numerical grid.

Check distinct problem regions and previously good regions separately. A better
endpoint, mean distance or native objective does not establish a better complete
structure. A global-only finer-matching failure does not establish how a local
finer-matching term will behave after a separate capture stage. Likewise, diagnose
surface representation and time integration before blaming endpoint intersections
on excessive fitting pressure. Preserve failed trials and the retained reference.

Record which symptom classes are represented by actual cases, which have only
diagnostic evidence and which remain untested. Do not convert workflow checks,
topology flags or the absence of a representative case into a validated automatic
correction rule. Keep production implementation and cohort qualification pending.
