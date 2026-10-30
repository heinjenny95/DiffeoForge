# Pilot priority and iteration decision contract

Owner instruction, October 28, 2026: **November 15, 2026 is the feature cutoff**.
Prioritize a usable, reliable pilot, reasonable waiting and reliable cancellation.
After the cutoff, stabilize the agreed functionality rather than expanding it.
Existing computations, accepted results and owner-paused side work remain protected.

This document fixes the implementation priority and acceptance contract. The
historical dev165 [intermediate-review implementation](PILOT_INTERMEDIATE_REVIEW.md)
provided accepted-state pauses after ten active minutes. The owner removed that
automatic pause on October 31: new attempts run to their native stop/cap while
preserving cancellation and effort reporting. Existing prepared/running studies
retain their recorded behavior; no limit or accuracy change compensates for the
removed pause.
The owner's acceptance goal is captured
projections and the right overall shape, with small surface differences allowed.

## First resolve effort versus actual improvement

An iteration limit is a computational allowance, not a surface-quality criterion.
An accepted optimization update may require several objective/gradient calls.
Record accepted updates, trial evaluations, active phase and elapsed time separately.
Do not estimate remaining useful work by multiplying a fixed step cost by a cap.

Before extending a difficult saved fit, examine its immutable accepted parameter
states at several earlier times. Verify the original control basis, nonzero
initial field, objective context, source and target. Read bounded NumPy arrays
without pickle execution; never restore an optimizer for this diagnosis. Evaluate
the fields on the identical original source and numerical grid, preserving all
existing evidence. Count the initial accepted state separately from optimizer
updates; callback/native state indexes can be offset by one.

Measure the complete surface, each marked region and the relevant individual
feature tips separately. A nearly unchanged regional percentile can conceal an
improving small projection. Conversely, a lower objective or better tip does not
establish a correct whole structure. Keep sampling sensitivity, numerical grid,
mesh validity and visual/anatomical assessment distinct. See the
[offline qualification protocol](PILOT_OFFLINE_EXPERIMENT_PROTOCOL.md).

## Required next pilot behavior

1. Show elapsed effort and the source-bound exported result without requiring
   periodic manual permission to continue optimization. Settled matching display
   previews remain sufficient for owner review; full detail is optional.
2. Keep the finite recorded iteration allowance and native stopping conditions.
   A budget stop stays **provisional**, with its field and termination evidence
   preserved. It must never be relabeled native convergence or final acceptance.
3. Base continuation advice on comparable objective history **and** observed local
   feature improvement, outside preservation and geometry checks. Insufficient
   evidence means uncertain, not a fabricated plateau. Do not silently double the
   cap or weaken tolerance, precision or final quality requirements.
4. Distinguish useful numerical work from a hypothesis about attachment scale,
   deformation capacity or alignment. A changed method/basis needs a separately
   declared trial. Preserve the better retained result when a trial regresses.
5. Keep cancellation responsive through the launch-bound supervisor. Save only
   finite accepted states; protect unrelated jobs and explain whether cleanup or
   export is active. Verify this on the actual packaged path before delivery.

The interval and budget are engineering choices requiring measurement, not
universal anatomical thresholds. Do not turn every preview interval into an
automatic restart from momenta: that discards L-BFGS/line-search memory and changes
the numerical trajectory. Prefer in-memory observation/accepted-state boundaries;
an actual later restart must disclose its new optimizer history. Time budgets
also require honest reporting of noninterruptible work and cancellation latency.

## Qualification before solver adoption

The separately authorized 2026 method experiment is closed at the owner's request;
retain its results separately from production and start no further variants.
Timing, preparation, export and independent quality checks must be reported
separately. Author-code speed claims are not established for a new anatomy merely
by importing the package. Retain divergent trials and repeated-run differences.
Check complete original geometry, distinct projections, endpoint intersections,
outside preservation and repeatability before choosing a candidate. Endpoint
validity alone does not prove an injective complete trajectory or biological
correspondence. Method-specific momenta/history cannot silently replace native
atlas trajectories or the cohort PCA metric.

Priority order until the cutoff: iteration/effort visibility and decisions;
reliable local fit qualification; cancellation and saved-result recovery; final
packaged workflow verification. Additional UI features and unrelated side work
must not displace these gates. No fixed iteration count or elapsed time is a
promise of a perfect fit on arbitrary specimens.
