# Supervised desktop Deformetrica execution

Status: **alpha; execution and cancellation are connected and the execution
worker is included in the prospective Windows evidence bundle**

DiffeoForge desktop can launch the exact Deformetrica configuration completed
in parameter review after its configured reference runtime passes the read-only
doctor check. The reviewed configuration hash, complete launcher identity, run
ID, and absent immutable destination are bound into one versioned launch
request. Refreshing or starting that request retains the same run ID, so the
destination shown to the user cannot silently change at launch.

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

Deformetrica can write optimizer output to timestamped `output/*_info.log`
files instead of its process stdout. The adapter tails both sources, de-duplicates
cross-source repeats, and flushes the observed stream into
`logs/deformetrica.log`. The worker sends only schema-valid lifecycle, activity,
and progress events on its protocol stdout.

After the parent accepts a completed run, a separate GUI task strictly imports
the estimated momenta and control points, publishes a source-bound linear PCA
snapshot, verifies it by recomputation, and only then unlocks Results & PCA.
This postprocessing is documented in
[verified PCA of Deformetrica momenta](REFERENCE_PCA.md).

## Progress and ETA meaning

Before launch, the review screen shows a deliberately broad, low-confidence
planning range. It scales an engineering workload heuristic by template and
subject face counts, cohort size, time points, RK2, relative control-point
spacing, CPU threads, and the configured iteration cap. It is neither a
hardware benchmark nor a convergence prediction.

Progress is derived from Deformetrica's own iteration and objective log lines.
The desktop displays the observed iteration, configured maximum iteration,
objective, attachment, regularity, and elapsed time. It does not claim that the
iteration count is a convergence percentage.

While Deformetrica is active but has not completed another logged iteration,
the worker emits a heartbeat every ten seconds. The first-iteration state is
shown explicitly with elapsed time and the latest native log message, so an
expensive initial objective and gradient evaluation does not look frozen.

After at least three measured iteration intervals, the tracker takes the median
seconds per iteration from a rolling ten-observation window and computes:

```text
ETA to iteration cap = (configured maximum - observed iteration)
                       * median observed seconds per iteration
```

The UI labels this value **ETA to iteration cap (not convergence)**. Before
enough observations exist it retains the broad planning range and says that the
live estimate is warming up. The observed value replaces the pre-run heuristic;
it remains a rate extrapolation, not a runtime guarantee, convergence forecast,
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

- The PyInstaller specification now includes the dedicated execution worker as
  a fifth sibling executable. The prospective v0.4 evidence build requires both
  hard-parent-death containment and a real queued-cancellation smoke before it
  can write evidence. A fresh clean-runner v0.4 observation and rebuilt
  installer are still pending; the currently installed preview is unchanged.
- Interrupted-run discovery and resume exist in the shared CLI services but are
  not yet exposed as guided desktop actions.
- Verified Deformetrica momenta and control points are imported into the shared
  PCA/result screen. Reference mean/positive/negative PC deformation meshes and
  registration renderings are not yet generated.
- Private-alpha builds can reuse an already verified same-owner WSL runtime.
  Public builds require the installer-managed runtime payload and its clean-host
  install/repair validation before release.
