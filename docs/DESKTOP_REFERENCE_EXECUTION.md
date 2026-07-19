# Supervised desktop Deformetrica execution

Status: **source-level alpha; execution and cancellation are connected, frozen
installer integration is not yet claimed**

DiffeoForge desktop can launch the exact Deformetrica configuration completed
in parameter review after its configured container environment passes the
read-only doctor check. The reviewed configuration hash, launcher engine,
container image, run ID, and absent immutable destination are bound into one
versioned launch request. Refreshing or starting that request retains the same
run ID, so the destination shown to the user cannot silently change at launch.

## Process and evidence boundary

The Qt window never runs Deformetrica in its own process. A Qt task starts a
Qt-independent parent controller, which contains a dedicated execution child in
a Windows kill-on-close Job before transmitting the request. The child then:

1. rechecks the configuration bytes, launcher settings, and destination;
2. runs the normal preflight service;
3. creates the immutable prepared run with the shared preparation service;
4. executes the existing external-backend adapter;
5. inventories terminal outputs; and
6. verifies the result report before emitting a terminal event.

The parent separately verifies the terminal state. Completed and interrupted
runs must pass the full result report and match the child's `result.json` hash.
A prepared-but-not-executed stop must pass the prepared-run verifier. A stop
before preparation must leave no destination. Protocol, exit-code, lifecycle,
hash, and filesystem contradictions fail closed.

Raw Deformetrica output remains in `logs/deformetrica.log`; the worker sends only
schema-valid lifecycle and progress events on its protocol stdout.

## Progress and ETA meaning

Progress is derived from Deformetrica's own iteration and objective log lines.
The desktop displays the observed iteration, configured maximum iteration,
objective, attachment, regularity, and elapsed time. It does not claim that the
iteration count is a convergence percentage.

After at least three measured iteration intervals, the tracker takes the median
seconds per iteration from a rolling ten-observation window and computes:

```text
ETA to iteration cap = (configured maximum - observed iteration)
                       * median observed seconds per iteration
```

The UI labels this value **ETA to iteration cap (not convergence)**. Before
enough observations exist it says that the estimate is warming up. The value is
an observed-rate extrapolation, not a runtime guarantee, convergence forecast,
or production-performance claim.

## Cancellation outcomes

Cancellation is phase-dependent and yields one of three nonfailure outcomes:

- `stopped_before_prepare`: no run directory exists;
- `prepared_not_executed`: the immutable prepared run exists, but Deformetrica
  never started; or
- `interrupted`: execution stopped, terminal evidence was written, and any
  inventoried checkpoint remains in the run.

Closing the window while execution is active requests the same cancellation and
keeps the window open until the parent reconciles a terminal outcome.

## Current limitations

- The dedicated execution worker is exercised from source and is not yet a
  sibling executable in the Windows evidence bundle or installer.
- Interrupted-run discovery and resume exist in the shared CLI services but are
  not yet exposed as guided desktop actions.
- Verified Deformetrica atlas outputs are not yet imported into the shared PCA
  and result screen. The GUI opens the verified run folder and states this
  boundary explicitly.
- The containerized Deformetrica runtime still has to be present and pass the
  exact environment check; DiffeoForge does not silently install or replace it.
