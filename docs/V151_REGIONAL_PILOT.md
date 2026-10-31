# v151 — regional feedback and guided pilot recovery

Owner authorization on 22 October covers the two open pilot UI follow-ups and
the proposed regional-feedback workflow. Older scientific, visualization and
external-platform gates remain separate. No owner/native fit is launched by
development, preparation, reviewing or delivery.

## Show the location without choosing LDDMM parameters

Once the original and reconstruction have rendered, **Show where this fit needs
improvement** opens a rotatable original-surface brush. Click a surface point,
adjust the radius and inspect the orange selected patch from other views. The
settled view uses original geometry. The brush selects whole original triangles
whose centres lie within a 3D sphere; it is not a 2D screen rectangle, geodesic
brush or anatomical correspondence. Nearby/back-facing surfaces within that
sphere are included and visibly inspectable. Up to eight areas per specimen are
supported, with a clear action for replacing the current specimen's areas.

A short symptom choice records missing detail, missed surface, wrong shape,
distortion or uncertainty. The explicit fit decision saves this structured
feedback in the existing hash-chained review journal, with specimen hash,
original-target coordinate space, 3D centre, radius and symptom. Closing without
recording discards edits. Historical free-text point notes remain readable.
Marking a region neither approves anatomy nor starts a job.

## Visible next steps and small hypotheses

Rejected fits expose a visible visual question and one explained proposal in
their own method card. No discovery of optional technical tools is required.
The hypothesis uses the selected symptom, marked patch size versus matching
width, the preceding rejected hypothesis and provisional iteration-cap status.
Possible tests change matching detail, deformation spread or attachment weight;
a previous detail rejection can lead to more local movement, then stronger
matching. This is a transparent heuristic, not an identifiable inverse mapping
from a screenshot to a correct parameter. Control-point density is not blindly
increased in response to missing detail.

When one preferred method fails a contrasting form, uncertainty proposes testing
the other method on that same form; that option is also directly available.
Each proposal declares one trial on one specimen, stays within the existing
screening budget and prepares a separate successor only. **Run prepared test**
remains explicit. Prior fits/reviews remain saved, event histories are appended,
and changed settings reset coverage approvals. Method changes retain only
compatible method/settings approvals. The normal contrasting-form and complete
joint confirmation gates still apply before numerical qualification.

Before a marked follow-up is prepared, its exact source reconstruction/settings
and original hash are bound and patch/global baseline measurements are captured
in background. Follow-up loading verifies those identities. Marked regions are
carried into a new inspection until explicitly changed/cleared. An exhausted
budget reports that fact and points back to alignment, mesh and template checks;
it does not silently extend the budget or restart a full-cohort grid.

## Regional and whole-shape assessment

Each marked original patch is area-sampled directly in two fixed-seed repeats,
so a small selected feature does not vanish from a whole-surface sample. Unsigned
point-to-triangle p95/p99 distances assess original-to-fit coverage; reverse
samples within the same sphere assess fit-to-original disagreement. An empty
reverse sample is unknown, never a perfect score. Whole-shape p95/p99, spatial
region tails and geometric warnings are checked alongside the selected patch.
The result reports improvement, regression or inconclusive evidence, with
sampling-repeat ranges and a declared 5%/scale-floor comparison heuristic.

No local attachment weights, cropped scientific surfaces, optimizer equations
or stopping rules change. Fits still deform the whole object. Closest-surface
distances do not establish anatomical correspondence, topology suitability,
biological validity or universally suitable settings. Human inspection remains
required even when measured distances improve.

## Separate method areas

Current and Varifold have simultaneously visible cards, each with its method,
computation/review status and independently bound **Inspect [method] fit** action.
There is no shared fit selector. Callbacks retain their candidate identity across
refresh/resize. While a batch computes, cards show progress without review or
decision actions. Aggregate/selection actions wait for required individual
reviews, allowing a technical failure to be distinguished from a visual rejection.
The reduced single-fit viewer and on-demand saved alternative comparison remain.

## Verification boundary

Synthetic regression and exact runtime GUI/geometry checks are recorded in the
delivery evidence. They exercise the reported tie/preference/rejection route,
visible local-detail/uncertain recovery, candidate binding, review persistence,
small-patch sampling, whole-shape regression protection and the existing rendering,
recording and explicit-execution guards. These checks do not establish successful
fits on an owner's cohort or independent first-use acceptance. Source, tested
package and installed runtime are tracked separately; installation requires a
fresh idle check and recoverable backup.
