# Bounded shared-model capture and detail

This is a separate, explicit common-model hypothesis after a measured shared-fit
plateau. It uses the existing native Deformetrica L-BFGS implementation with the
qualified full-target singleton guard. It is not a replacement numerical solver,
an automatic recovery mechanism, or a guarantee for every anatomical dataset.
Explicit About the same/Worse feedback on a failed parameter contrast can choose
this qualified hypothesis directly; exhausting another old detail/weight contrast
is not required. Improving feedback and numerical warnings retain their gates.

## Model and support

All individually suitable forms must retain their verified reviews and original
cohort. The initial common protocol supplies the scale reference. An already
adopted broad/detail protocol reuses its original family; its kernel is not
halved again for each form.

New v2 hypotheses use half the reference deformation width and half its noise
standard deviation. The shared basis retains the original common sites and the
union of approved complete-field sites, including preserved prefixes and local
additions. Compatible sites from an unapproved contrast are excluded. The largest
complete approved-field count is the minimum capacity.

The selector adds farthest points from the original source surface until both
the minimum capacity and measured coverage are met. Coverage requires the most
distant sampled source location to be within one proposed deformation width of
a control site. The deterministic sample uses 8,192 equal-area points, up to
65,536 source vertices, and seed 2026110207. Preparation records the approved
demand, retained sites, added sites, and measured coverage. The preparation
action and candidate card display the selected count. The resource ceiling is
2,000 sites. Exceeding it blocks preparation with an explanation.

Control sites represent locations. Reuse of those sites does not transfer any
momenta between forms. Coverage is a sampled geometric criterion for a fit
hypothesis. Each result still needs the usual quality checks and review.
Earlier v1 preparations and adopted v1 families keep their exact saved basis
and two-stage contract.

Each new form starts its own capture from native zero momenta on the same original
template and control basis. Capture uses attachment width twice the new
deformation width, followed by detail at 0.45 times that width. The deformation
kernel, noise, original source, and controls stay identical between these stages
and across forms. Singleton checks freeze template and controls, use Float32 and
37 RK2 time points, and retain or tighten the reference tolerance to at most 1e-6.

## Finite execution and stopping

The two objectives are declared before execution, with at most 120 native
iterations each. Detail copies the complete same-form capture momenta after its
checks pass and starts fresh optimizer history. A capture is a computational
checkpoint, not an invented suitability review. No automatic ten-minute review,
third objective, unchanged extra-iteration loop, or optimizer recovery is added.
A native cap remains a cap, not evidence of convergence.

The normal worker/controller executes both stages and propagates cancellation.
Cancellation before detail dispatch starts no additional native work. A prepared
detail remains separately reopenable. A completed checked capture also has an
explicit preparation action for its declared detail; it is not recalculated.
The direct, hash-bound successor is reused even if later forms have successors.

Native source/target/field identity and finite accepted-state checks precede
reuse. Capture additionally requires ordinary fixed-field quality, a bound
evaluated endpoint, no geometry warnings, and finite whole-surface repeat P95
within 15% of target diagonal. Failed checks do not start detail. Ordinary quality
retains the independent original-source sampling, temporal, actual optimizer-grid,
and native-export reproduction gates described in [field quality](ORDINARY_FIELD_QUALITY.md).
Mesh display proxies never replace those scientific inputs or checks.

Reported effort includes the capture's actual iterations plus detail's own
counter, identifies the two objectives, and keeps fresh history explicit. Displayed
combined time includes both stages' recorded fitting and checking time. It does
not assert an uninterrupted optimization trajectory or equate 240 steps with
240 steps on one unchanged objective.

## Review, adoption, and joint confirmation

The final detail result has one explicit common-result review destination and
compares against that form's retained accepted individual fit. Suitability and
Better/About the same/Worse remain separate decisions. Earlier fits, annotation
history, individual reviews, and old common-model decisions are preserved.

Adoption of a reviewed suitable detail model is explicit. Subsequent forms use
that exact family and basis with their own capture and detail. A stopped or
rejected final detail does not propose another copy of the same hypothesis.
The capture alone cannot be adopted as the finished common protocol.

Only matching-model, explicitly suitable singleton fields can initialize joint
confirmation. The original project's joint optimizer and template/control update
choices are preserved separately from singleton L-BFGS/frozen settings. Joint
optimization can still change individual shapes and requires its own checks and
review. Individually suitable or numerically qualified fields do not approve a
joint atlas, full-cohort result, or PCA.

Joint confirmations initialized from this new profile explicitly enable shared
fixed-field qualification. This evaluates the final estimated template, final
control locations and complete ordered momenta without further optimization.
Every form uses one conforming material-source grid. Native-export reproduction,
adaptive 37/73/145/289/577 Float64 RK2 evaluation, actual optimizer-grid accuracy,
and zero detected intersections/nonpositive faces must pass with the same
criteria as the singleton checks. Source refinement adds material points and
evaluates the unchanged field; it does not repair fitted endpoints or alter the
native template/coefficients. The checker has the same 500,000-vertex and
16-pass bounds. Its exact per-form endpoints, hashes and shared source binding
are used for measurement and review. Earlier joint contracts remain unchanged.

An unresolved final check remains an inspectable result with a failed numerical
selection flag. Identity changes or missing native data fail closed. Neither
case manufactures approval or changes the stored successful individual fits.

## Verification scope

Generic support/physics parity is checked independently against separately
qualified local fields. Public tests cover finite dispatch, cancellation before
and during detail preparation, geometry/identity vetoes, review destinations,
retained reviews, adoption, next-form progression, direct successor reopening,
actual effort accounting, and original joint choices. Receipt-controller journeys
explicitly use synthetic tensors and do not establish mathematical fit quality.
Native worker lifecycle and dataset qualification are separate evidence gates;
source tests alone do not establish installation or anatomical approval.
