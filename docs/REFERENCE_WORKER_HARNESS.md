# Nonnumerical reference worker pipe harness

Status: **real child-process transport; guaranteed stop before preparation**

The harness is the first executable consumer of the hash-bound reference
prelaunch request and the separate reference worker event protocol. It exists to
prove the stdio boundary before any mutating run preparation or Deformetrica
execution is connected.

## Behavior

The module reads exactly one JSON request line from stdin, reconstructs the
schema-valid `DesktopReferenceLaunchRequest`, and emits JSON Lines to stdout. A
second line or any other trailing input is rejected rather than ignored. A
successful stream contains:

1. `accepted`, bound to the exact request ID, config hash, and destination;
2. phase `verify_request`;
3. terminal outcome `stopped_before_prepare`.

Request verification occurs inside the child process and repeats the config
hash, parsing, launcher, output-resolution, run-ID, and destination-nonexistence
checks. A parsed request that fails verification produces terminal `failed` and
exit code 1. Malformed input or unsupported command-line arguments produces a
protocol message on stderr, no event stream, and exit code 2.

## Non-mutation guarantee

The harness never imports or calls `prepare_run` or `execute_run`. It does not
invoke the environment doctor, Docker, Deformetrica, or another child process.
It creates no output root, destination, XML, manifest, event file, log, or
result. Unit and real-subprocess integration tests inventory the complete test
project tree byte-for-byte before and after the pipe round trip.

## Parent controller

A separate Qt-independent controller now launches this harness, assigns it to a
kill-on-close Job Object on Windows before writing the request, bounds stdout and
stderr, enforces a timeout, reconciles the exact three-event lifecycle and exit
code, and independently repeats request and destination verification. See
[the nonnumerical reference harness controller](REFERENCE_HARNESS_CONTROLLER.md).

The Windows one-directory evidence bundle exposes the same module as the
sibling `DiffeoForgeReferenceWorker.exe`. Its build cannot publish v0.2 freeze
evidence unless that executable completes the controller round trip with exactly
three events, outcome `stopped_before_prepare`, exit code 0, empty stderr, and no
destination. Legacy v0.1 evidence remains verifiable but does not claim this
third entry point.

## Current boundary

This is not the production reference worker. The harness has no cancel reader,
descendant process, preparation, result verification, recovery, resume, or GUI
wiring. Its terminal stop and the controller's verified result are engineering
transport evidence, not a completed atlas and not scientific evidence.

The separate shared-core
[approved preparation service](REFERENCE_APPROVED_PREPARATION.md) is now
consumed by a new source-level
[approval-bound preparation worker](REFERENCE_PREPARATION_WORKER.md). It is
deliberately not wired into this v0.1 harness, controller, or frozen evidence.
