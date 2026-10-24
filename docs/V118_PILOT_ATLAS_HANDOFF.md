# v118 — preserve pilot fits and inspect the atlas early

Previously, completing a pilot retained its learned template and control points
but initialized every full-cohort momentum row to zero. A good pilot fit therefore
did not carry its deformation field into the atlas initialization. This can be
a contributor to different fits; it is not proof that zero initialization is
invalid or the sole cause of any registration failure.

New completed pilots bind their exact ordered momentum rows to the full aligned
cohort on the same learned template/control basis. The other rows initially start
at zero and are fitted individually against that fixed common basis, using the
same native GradientAscent equations and spatial/matching settings. These fields
are initialization for one subsequent joint atlas, not final fits or separately
computed rows spliced into a PCA. Initializer stop logs are stored per specimen
so they cannot be misinterpreted as the joint atlas's stop signal.

The joint atlas pauses after up to 10 accepted iterations, or an earlier native
stop, before a complete trajectory export. Ten is a declared engineering review
checkpoint, not a convergence or anatomical-error threshold. The initial common
state, native checkpoint, preserved-pilot endpoints and early joint endpoints
are inventoried. Human review compares each pilot reconstruction with its staged
original and optionally with the preserved pilot endpoint. Approval is bound to
the exact checkpoint and comparison hashes. Rejection, missing review or changed
evidence blocks continuation. An approved continuation creates an immutable
successor; verification and preparation run in background, and calculation does
not start automatically. Final full-cohort QC is still required.

Interrupted initialization records completed rows against the saved checkpoint.
Compatible resumes retain those rows. Native resume restores parameters and
iteration, but reinitializes objective baseline, gradient and line-search history;
an identical optimizer trajectory is not promised.

For an older completed pilot, **Prepare atlas with saved pilot fits…** creates a
separate, linked configuration. It verifies the exact selected seed and original
aligned cohort. Existing configurations, atlas runs and PCA snapshots remain
unchanged. This route requires a new atlas; it cannot repair an existing PCA.
Compact checkpoints and GradientAscent are required for this initialization.

## QC and PC-shape usability

Full-atlas visual QC has **Show next specimen →**. It moves through the visible
specimen list without saving a decision or silently approving a specimen, and
stops at the last item. Choose **All specimen meshes** and clear the search to
inspect the full cohort. Existing automatic advance after a saved decision is
retained. Both pilot and atlas overlays now use subdued orange original lines
and an opaque blue reconstruction surface, with matching labels and Plan B copy.
These are display changes; scientific geometry is unchanged.

PC-axis Shooting uses the corrected launcher-directory policy documented in
[the launch note](V118_PC_SHOOTING_LAUNCH.md). The existing live optimizer plot
and +300-iteration continuation remain available.

## Verification and limits

Identity/order, changed-source, checkpoint/resume, stale/rejected/incomplete
review and non-mutating navigation regressions accompany the change. A bounded
native Deformetrica 4.3 CPU test exercised five synthetic subjects, exact pilot
field preservation, early pause, recorded test-only review and joint resume.
An independent one-subject native fixed-basis fit reproduced the initializer
momentum row with maximum absolute difference zero. Native Shooting completed
from a 295-character design path with unchanged source evidence. Synthetic Qt
checks exercise the actual checkpoint overlays and both display colors.
The broad final regression group passed 167 tests with one dependency-related
skip; an overlapping 136-test group covered PCA publication and QC. After the
background-resume refinement, 48 handoff and desktop-QC tests passed. Ruff and
diff checks passed.

These tests establish software behavior, not biological validity, better fits
for every cohort, cross-platform qualification or a runtime guarantee. Owner
anatomical acceptance, parameter sensitivity and the full-cohort result remain
separate. Local build/install evidence is recorded separately.
