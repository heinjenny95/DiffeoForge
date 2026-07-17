# Nonnumerical reference harness controller

Status: **contained parent supervision; guaranteed stop before preparation**

This Qt-independent controller is the first parent-side consumer of the
nonnumerical reference worker harness. It proves launch, containment, bounded
transport, timeout, lifecycle reconciliation, and independent parent
reverification before run preparation or external-engine execution is connected.

## Launch boundary

The controller independently verifies the hash-bound
`DesktopReferenceLaunchRequest` before creating a process. On Windows it creates
the existing kill-on-close Job Object, launches the child without a console, and
assigns the child to the Job before writing any reviewed request bytes. A failed
launch or Job assignment stops the process and fails closed.

The parent writes one canonical UTF-8 JSON request line and immediately closes
stdin. The source command is
`python -m diffeoforge.desktop.reference_worker_harness`. Frozen desktop code
resolves the sibling `DiffeoForgeReferenceWorker.exe`. The Windows evidence
build now includes that entry point and must pass the same controller round trip
before freeze evidence is created. This packages only the nonnumerical harness;
frozen reference atlas execution remains disabled.

## Bounded supervision

Stdout is read as strict UTF-8, LF-terminated JSON Lines. Each line has a fixed
byte limit, blank or unterminated lines are rejected, and the controller accepts
at most the harness's exact three events. Stderr is drained concurrently into a
fixed-size byte buffer with an explicit truncation marker. A finite supervision
timeout terminates the process; closing the Windows Job handle also terminates
assigned descendants if a future or adversarial child creates them.

The existing `ReferenceWorkerEventLedger` validates request identity, contiguous
sequence, config hash, destination, phase order, terminal evidence, and absence
of post-terminal data. This narrower controller additionally requires exactly:

1. `accepted`;
2. phase `verify_request`; and
3. terminal `stopped_before_prepare` with exit code 0.

A schema-valid terminal `failed` is preserved as a typed execution error and
requires exit code 1. All later lifecycle outcomes are rejected because this
controller launches only the nonnumerical harness.

## Independent success check

After the child exits successfully, the parent rereads and reparses the bound
configuration, rechecks its SHA-256, launcher identity, output resolution, run
ID, and destination nonexistence. Success is returned only if the terminal
evidence and the real filesystem both still show no destination. Tests cover the
real subprocess, process-containment failure, a Windows timeout that kills a
spawned descendant tree, malformed and adversarial streams, oversized output,
bounded stderr, unterminated lines, changed parent evidence, and an unexpected
child-created destination.

## Current boundary

This is not reference atlas execution. The controller sends no cancel command,
does not invoke Docker or Deformetrica, does not prepare a run, and is not wired
to the GUI. It proves the source and frozen parent/process boundary only. The
frozen build now also hard-exits a real controller after assigning a suspended
reference worker and requires Job-driven worker termination; see
[the frozen parent-death evidence](FROZEN_REFERENCE_PARENT_DEATH.md). The next
gate is a separately reviewed preparation-only lifecycle before any numerical
process is reachable.
