# Run management and live telemetry

Status: **implemented lifecycle management; no unsafe in-process suspension**

The desktop compute page is the active-run centre. It shows the reviewed
destination and engine, current workflow phase, optimizer observations, an
append-only event view, cancellation state, and independently reconciled terminal
result. The start page provides bounded discovery for completed results,
interrupted Deformetrica runs with verified checkpoints, and nonterminal runs left
after a crash. Remote execution keeps a persistent reconnect folder and does not
implicitly cancel a server job when the app closes.

## Progress and ETA

Reference progress is learned from committed Deformetrica log observations. After
enough iterations, DiffeoForge reports a robust observed seconds-per-iteration
rate, time to the configured iteration cap, and—only when the recent objective
trend is stable enough—a bounded likely stopping window. The cap ETA is an upper
bound, not a convergence forecast. The trend window is labelled an estimate and
disappears when it is not defensible. Slowdown relative to the earlier observed
rate is reported as resource contention.

Modern progress counts exact completed workflow stages and committed optimizer
decisions. It does not turn those counts into a fictitious elapsed-time percentage
or runtime ETA.

## CPU, RAM, and GPU

During a local reference run the contained worker samples the visible backend
launcher process and descendants at the same bounded cadence as live activity:

- summed process-tree CPU percentage;
- summed resident memory (RSS) and system RAM percentage;
- number of visible processes;
- for requested CUDA execution, optional `nvidia-smi` whole-device utilization and
  memory.

The UI states the attribution boundary. WSL and containers can hide work from the
Windows launcher tree, and NVIDIA device totals can include other programs. These
observations are not peak-memory guarantees, cost estimates, or proof that all GPU
load belongs to DiffeoForge. Missing `psutil` or `nvidia-smi` produces an explicit
unavailable state and never fails an atlas.

## Checkpoint stop and resume

DiffeoForge does not suspend a live Deformetrica process in memory. Such a pause
would be unsafe across native, WSL, and container launchers and could leave output
writers or opaque optimizer state inconsistent. The supported equivalent is:

1. request contained cancellation;
2. preserve terminal evidence and any inventoried Deformetrica checkpoint;
3. discover and fully verify the interrupted run;
4. create a new immutable resume successor from that exact checkpoint.

The source run is never overwritten. If no checkpoint exists, the desktop says so
and does not advertise resume. Crash recovery additionally requires the researcher
to confirm that every writer has stopped before retained output is hashed or a
terminal event is reconciled.
