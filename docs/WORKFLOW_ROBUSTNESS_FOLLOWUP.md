# Workflow robustness follow-up — source only

An owner-requested review of the new source interface reproduced four concrete
failures on the unchanged preceding source commit: a changed non-candidate mesh
could leave a template recommendation usable; reanalysis left the old result
applicable; two-coordinate results still offered PC3; and one-coordinate results
produced an empty score view. This follow-up corrects those cases.

## Template selection

The selected candidate remains visible in a dropdown. Its explanation follows
that choice, distinguishes a contrasting alternative and retains unreadable-input
warnings. A fresh analysis or changed file-pattern/project context immediately
retires old choices.

Applying a candidate checks every ranking input's SHA-256 in a background worker,
using bounded chunks and cooperative cancellation without parsing mesh geometry.
The callback rechecks membership and file identities before changing the selection.
Duplicate clicks, cancellation, a new preparation or changed files cannot apply
the pending result. Unreadable files retain their available content binding;
an unbound file must be inspected and the recommendation renewed. No file is
silently excluded from atlas inputs. Preview dialogs are disposed on closing.

This verification adds input-read work at an explicit selection boundary; it is
not a claim that hashing large cohorts is free or that fitting became faster.

## Saved views and export

PC-pair choices follow the saved dimension count. A one-axis result has a labelled
PC1 score line with no PC2 coordinate. All-pairs shows only existing pairs, with
unchanged score values. Tabs with no prepared media are disabled and explained.
Current-view exports follow actual display readiness. 3D loading publishes its
ready/error state, releases the completed future and keeps a failed view blank
and unexportable. Clearing a result clears old media and its export state.

The R dialog lists missing or selected sources, checks CSV existence before
offering geomorph, states the supplied units and calls the output a data ZIP.
Its complete source/table/archive verification remains at export time. No R
package is installed or launched by the interface.

## Boundaries

The expanded regression review also reproduced an existing pilot-review error:
the periodic rendering status immediately replaced a selected-pair load failure.
That error is now retained in the compact view's visible source heading as well
as its status, the idle display timer stops, and decisions remain gated. The
source heading follows the selected pair immediately, before loading finishes.
Selecting/reloading a new pair clears the error; stale callbacks for a
different pair cannot replace it. Optional full-detail failure still permits a
correctly bound settled preview. No fitting or approval rule changes.

A combined-run trace also reproduced a pre-existing 14-pixel viewport cycle:
replacing a retained hidden hint with a longer waiting message changed its
wrapping height and invalidated the image which hid it. After a pair's first
presentation, repainting keeps the base hint text and size while the canvas
shows its pending-frame banner. Decisions still require the current settled
image. The small-pair regression now observes readiness, viewport dimensions
and render count across repeated event-loop passes rather than one instant.
The problem-region action also uses the existing outlined secondary-button
style so it remains recognisable as a button in the native review window.

These are interface, provenance and display changes. There is no change to the
atlas objective, fitted parameters, optimizer, numerical acceptance thresholds,
PCA method or anatomical approvals. Only public synthetic fixtures are used for
regressions and native/offscreen UI review. Existing owner tests and fits are
untouched. The installation deferment remains in force: no installer build,
version bump, installation or upload is authorized by this source follow-up.

## Verification

The final combined source regression passed all 99 checks across template
freshness/cancellation, R handoffs, method results, saved media and pilot review.
After the final outlined-button adjustment, all 28 targeted review/lifecycle
checks passed again. Native Windows and offscreen Qt each passed 12 saved-view
cases across one/two/three axes, light/dark themes and two window sizes. The
same isolated UI harness verified selected-alternative application and both R
source states. A native pilot check verified visible failure/provenance,
disabled decisions, stale-error rejection and a stable recovered viewport and
render count. Settings were isolated and only synthetic fixtures were used.

The final combined small-pair trace settles with two frame renders and a stable
viewport; the prior trace repeatedly switched height by 14 pixels and reached
13 frame renders in under half a second. This demonstrates removal of that
layout loop, not a general speedup for first-time dense mesh preparation.
Full repository lint, whitespace and 180 relative documentation links passed.
Practical acceptance on the owner's current pilot still awaits owner feedback.
