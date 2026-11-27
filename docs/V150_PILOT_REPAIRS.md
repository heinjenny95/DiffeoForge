# v150 — pilot first-use repairs

Status update, 23 October 2026: the owner again reports whole-cohort loading
during pilot preparation after these repairs. The overall issue is reopened in
the [next-version plan](NEXT_VERSION_PLAN.md#repeated-cohort-loading-before-pilot-selection--reopened-23-october-2026).
The delivered checks below establish specific reuse paths, not resolution of
this current end-to-end report. Its active cause has not yet been traced.

Owner authorization on 22 October replaces collection-only scope for the recently
reported pilot issues. Existing studies, recorded reviews and scientific outputs
remain readable. These changes do not start or repeat a scientific fit.

## View transitions and decisions

The previous content cleanup deleted only top-level widgets. Children of nested
layouts survived refreshes, explaining duplicated selectors/actions and clipped
controls. Cleanup now recursively hides, detaches and schedules those widgets for
deletion before building the next view. The reusable screening panel is preserved.
Inspection resolves the currently selected candidate, including after refresh.

During a batch the guided view presents progress and safe cancellation. Review and
decision paths appear after computation; Both good/unfit require the corresponding
recorded individual reviews. Available Run/Inspect/Continue actions use the shared
primary style, including immediate repolishing after state changes. Disabled
running actions lose primary emphasis.

The viewer hides its decision panel until both surfaces have actually reached a
usable displayed comparison. Loading a different pair or a display failure hides
it again; closing remains available. Once displayed, its geometry identity keeps
the layout stable through rotation/repainting while readiness still gates clicks.
Hidden controls retain their small layout reservation to avoid invalidating the
render by repeatedly resizing its viewport. Approval is never inferred from a
completed optimizer or an image alone.

## Saved alignment and bounded loading

Preparation checks existing aligned evidence before creating a new GPA preview.
Fresh hashes, ordered source names, landmarks, settings, preprocessing version and
the reconstructed fingerprint bind reuse. Existing raw/aligned copies and evidence
companions are still verified; source bytes are checked again after reuse. This
works after reopening and with non-VTK originals. Different inputs/settings cannot
reuse that publication. Approved-preview reuse also checks current original bytes.

Cold preview measurements now release each parsed surface before loading the next;
the previous tuple retained all full meshes simultaneously. Progress distinguishes
file checking from saved alignment reuse. Hash I/O across the cohort remains
necessary and is not described as mesh parsing or a universal speedup. Scalar
measurement caches continue to serve parameter analysis and pilot selection.

## Starting-template suggestion

Overall radial/spectral shape and local surface summaries have equal family weight.
Local summaries area-sample occupancy and sign-independent normal variation at four
size-normalized neighborhood scales, with 8192 samples and 256 anchors per mesh.
Finite sampling is approximate; it is not a correspondence or deformation model.
Noise floors and family normalization limit amplification of small sampling changes.
No anatomy-specific feature count or preference for fewer features is encoded.

The UI discloses close scores and offers a contrasting alternative alongside ranked
options. The user still previews and explicitly chooses a template. Content-bound
scalar caches avoid reparsing unchanged templates for a repeated suggestion.

Up to 64 verified studies / 1024 directories / nine levels under the selected
project are searched read-only for compatible review evidence. Exact source bytes
or a verified original/aligned mapping associate it with the candidate. Details
retain source study, targets/hashes, method and model settings. Changed evidence is
ignored. Rejected fits do not blacklist templates or alter ranking; evidence from
other targets/settings is not treated as a universal verdict. Changing projects
invalidates the displayed suggestion. This bounded lookup is not all-project history.
The original/aligned mapping uses the configuration's root preprocessing record;
its evidence hash and containment are checked before attaching past reviews.

## Verification and limits

Synthetic regression cases cover repeated refresh before deferred deletion,
selected-candidate binding, resize transitions, running/ready primary styles,
premature decisions, first displayed frame, pair switch and display failure.
Additional cases verify warm/reopened VTK and OBJ reuse without mesh parsing,
source/settings/output invalidation, one-live-mesh cold preview, local indentation
sensitivity versus retriangulation, cached suggestions and contextual review binding.
Existing preparation, method, descriptor, review and recorder checks remain separate.

Exact frozen/installed probes and delivery evidence are recorded separately after
build verification. Native scientific fitting, independent owner acceptance,
biological template suitability and large-cohort timing/RSS qualification are not
established by synthetic tests. No native stopping rule, optimization equation,
scientific geometry, historical decision or server run is changed.
