# Ten-minute review of a new regional pilot fit

## Owner update — 31 October 2026

New pilot attempts no longer declare the automatic ten-minute pause. A new
candidate clears an inherited review declaration from its seed and runs until
its ordinary native stop/cap, with unchanged limits, numerical guards, export
and anatomical review. Cancellation remains available. Existing prepared/running
contracts, saved review receipts and decisions remain supported unchanged.
Already prepared attempts retain their recorded behavior; prepare a new local
attempt to use the current policy. The implementation description below records
the historical explicit review contract, not the current default.

The owner-defined pilot goal is to capture the important projections and the
overall shape. A perfect surface match is not required. The first useful review
should be offered after about ten minutes of active optimization; this is not a
promise that a difficult fit will be finished within ten minutes.

Newly prepared, guarded regional singleton trials in dev165 declare
`accepted-pilot-review-v1`. At the next accepted native step after 600 active
seconds, optimization waits with its existing L-BFGS history in memory. A bound
preview shows the actual cached native deformation. The researcher can allow
another ten minutes or finish optimization at that accepted state. Review waiting
does not consume the next active-work allowance. The iteration cap, objective,
tolerance, precision, integration and numerical guards remain unchanged.

There is no automatic cap doubling for a new same-objective regional successor.
Its existing cap is retained, and explicit intermediate decisions control effort.
A native cap or tolerance can still end the run before the next review. An
individual objective/line-search evaluation is not interrupted just to meet a
clock deadline: the first review can therefore arrive later than ten minutes.

## Bind the view and preserve the computation

The preview is published only when the accepted parameter state matches the most
recent finite objective/gradient evaluation. An older cached vector is never
paired with a later trial's geometry. Coordinates and parameters are saved as
immutable, finite NumPy arrays, associated with the manifest, source object,
accepted-state index and objective. This performs no additional objective or
gradient evaluations. Display proxies are sufficient for review; full detail is
available explicitly and loads away from the GUI thread.

Decisions identify a specific review generation, nonce and manifest. Publication
is atomic and cannot overwrite a concurrently submitted decision. Changed arrays,
sources, model declarations or stale views cannot dispatch a decision. The
existing supervisor owns cancellation throughout the waiting phase. Closing or
losing a process does not authorize an automatic restart.

Continuing returns to the same native callback and optimizer. Finishing uses
native callback finalization, with a separate review-stop receipt, finite accepted
parameters and normal guard return. The result is labelled
`pilot_review_request`, **not convergence**. Ordinary export, geometry, preservation
and visual checks still follow; ending optimization does not approve anatomy or
a shared atlas/PCA configuration. Existing suitable-fit decisions retain their
meaning: remaining refinement is optional. Activity after an explicit finish is
labelled export/checking with no more fitting; review waiting is excluded from
optimizer progress-rate estimates.

The incoming native working surface is shown during a pause. A composed residual
field still requires its ordinary original-source evaluation after finalization;
the preview does not replace that check. Private meshes and checkpoints remain
in their project. Existing prepared manifests, running fits, ordinary atlas/PCA
and unguarded legacy studies do not opt into this new review policy.

The already loaded adapter also removes its run-local `PYTHONPATH` from helper
children, avoiding a compiler Python process attempting to initialize the same
active guard. The current interpreter retains its loaded adapter and module path;
no installed native runtime is edited.

## Verification and limits

Generated source and manifests protect the extra observer module; legacy guarded
configurations without the new declaration retain their previous engine bytes.
The observer parses under the pinned Python 3.8 runtime. Unit and Qt tests cover
active-time accounting, initial/capped/cached-state exclusions, changed arrays,
stale decisions, optional full detail and one-decision GUI behavior.

New small synthetic native CPU fixtures compare uninterrupted optimization,
pause/continue and an early reviewed finish. Objective/accepted-state sequences
and saved parameter/gradient array bytes agree for pause/continue; early finish
retains the corresponding prefix and completes the normal bound export. Timing
is forced in this fixture to exercise the ten-minute boundary without waiting;
the protected production interval remains 600 seconds. This verifies process and
numerical preservation, not ant fitting quality or a per-step throughput speedup.

Native Windows views at three window sizes and source worker/stop classification
checks are separate from exact-package and installation verification. A stale
appearance fixture failed identically on the previous source; its assertion now
compares the pilot with the current main-window palette instead of an obsolete
hardcoded color. No application appearance change was needed.

The exact-package and installed-runtime checks subsequently passed for dev165;
see the [delivery record and remaining practical check](V165_DELIVERY.md).
