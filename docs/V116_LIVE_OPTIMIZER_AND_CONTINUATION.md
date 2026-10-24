# v116 — live atlas objectives and explicit iteration extensions

The full-reference atlas Run page now draws finite, complete iteration events
from the existing supervised worker. The objective/log-likelihood curve is
visible during execution; Attachment is optional and Regularity uses a separate
panel and scale. Rendering uses Qt directly, retains at most 5,000 observations,
and performs no mesh reads or optimizer work. Duplicate/regressing events are
ignored. The view labels observed session iterations, clears for a new run, and
keeps the final observations after termination. Full retained logs and verified
result plots remain the complete evidence; a live curve is not anatomical QC.

After a successful native gradient-ascent run reaches its configured iteration
limit, **Continue +300 iterations** appears in the Run result card, QC footer and
saved result's optimizer card, including after reopening before QC release.
It shows the old/new limit
(e.g. 300 → 600), verifies the source checkpoint in a background task, and opens
the explicit **Start +300 iterations** summary. Choosing this does not immediately
start a computation. Numerical tolerance stops and line-search failures do not
offer the capped-run action; interrupted/failed recovery retains its existing
separate workflow.

Execution verifies terminal lifecycle/result consistency, retained log/CSV,
protected inputs, backend identity and the inventoried checkpoint. It copies
that checkpoint into a new immutable successor, increases only the protected
effective iteration budget, and records the old limit, +300, new limit and source
log hash in protected resume provenance. Existing results and QC decisions stay
with the source; new outputs need their own review. Chained extensions use the
immediate source's effective limit (300 → 600 → 900), even though the original
source configuration remains unchanged. The supervisor observes the actual
prepared effective budget rather than the original configuration's old limit.

Desktop launch request 0.3 carries the explicit additional budget; 0.2 remains
readable as zero additional iterations. Existing resume provenance remains
compatible; completed-source provenance requires the explicit extension record.
The native Deformetrica 4.3 state restores parameters and iteration but resets its
objective baseline, gradient and line-search sizes. An identical trajectory or
an eventual convergence guarantee is not implied. This change does not change
scientific model settings, impose a wall-clock timeout, or start a private fit.

Verification passed 171 scoped regressions (one dependency-presence skip),
Ruff/diff checks and offscreen visual inspection. A final accessibility follow-up
passed 129 overlapping UI/registration regressions (one skip), including a capped
run whose QC is still unreleased. Tests cover bounded/finite Qt
rendering, resumed indices, engine reset,
real button dispatch, legacy/new request contracts, protected source preservation,
300 → 600 → 900 chaining, tampered checkpoint/history rejection, other stop
signals, and the supervisor's extended progress budget. A real Deformetrica 4.3
synthetic test restored iteration 4 into a successor limited to 304, stopped
normally at 131, retained nine final VTKs, and left the source byte-identical.
These are scoped engineering checks, not private-cohort scientific acceptance.

The verified installer and local installation state are reported separately in
[V116 delivery](V116_DELIVERY.md). Do not update a running application/backend.
