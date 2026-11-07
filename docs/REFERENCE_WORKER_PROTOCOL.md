# Versioned desktop reference worker protocol

Status: **versioned phase-dependent transport used by the source and frozen
execution-worker boundaries**

The external Deformetrica lifecycle cannot reuse the Modern worker's
nonpublishing cancellation semantics. A Modern cancellation removes private
temporary work and guarantees that no destination was published. A reference
run can instead be stopped in three materially different states:

- before preparation, with no destination;
- after an immutable prepared run exists but before engine execution; or
- during engine execution, with a terminal interrupted result and possibly an
  inventoried checkpoint.

## Transport documents

`desktop-reference-worker-command-v0.1.json` defines one request-bound cancel
command. `desktop-reference-worker-event-v0.1.json` defines UTF-8 JSON-compatible
event envelopes with a contiguous zero-based sequence and one of five kinds:

- `accepted`: exact engine, config hash, destination, and the explicit
  `phase_dependent` cancellation contract;
- `phase`: a strictly advancing lifecycle phase from request verification
  through result verification;
- `activity`: a strictly increasing elapsed-time heartbeat emitted only during
  `execute`, including whether the worker is still computing the first complete
  iteration or is between later optimizer observations, plus the latest native
  Deformetrica log message;
- `progress`: a strictly increasing Deformetrica iteration observation emitted
  only during `execute`, including objective terms, elapsed time, and a clearly
  bounded ETA-to-iteration-cap; or
- `terminal`: one of `completed`, `stopped_before_prepare`,
  `prepared_not_executed`, `interrupted`, or `failed` with destination and
  result-hash evidence appropriate to that outcome.

## Parent-side ledger

The Qt-independent ledger is constructed from the immutable prelaunch request
and binds acceptance to its request ID, configuration hash, and exact
destination. It rejects a different request ID, hash, destination, sequence gaps,
repeated acceptance, phase repetition or regression, activity or progress
outside execute, non-increasing activity time or iterations, non-failure terminal data without acceptance, a
completed outcome before `verify_result`, stop outcomes
that contradict the observed phase, post-terminal data, and a stream ending
without a terminal event.

The schema also couples outcome to evidence. Completed and interrupted outcomes
require an existing destination and a 64-character result SHA-256. A stop before
preparation requires no destination or result. A prepared-but-unexecuted stop
requires the destination but no result hash.

## Current boundary

A dedicated execution worker now consumes this protocol in source and frozen
layouts. Its parent controller provides a bounded pipe reader, Windows Job containment, strict
event/exit reconciliation, configuration and iteration-cap binding, and
independent terminal verification. Desktop step 3 transports only validated
events into Qt and enables launch only after the read-only environment check.
See [supervised desktop Deformetrica execution](DESKTOP_REFERENCE_EXECUTION.md).

The prospective v0.4 Windows bundle gives the execution path its own sibling
executable. Evidence creation requires hard-parent-death containment plus a
queued-cancellation smoke that must stop before preparation without creating a
destination or starting Deformetrica. A fresh clean-runner observation and a
rebuilt installer are still pending. Guided recovery and resume remain open;
strict momenta/control-point PCA import is connected after a completed run.
The original deliberately nonnumerical harness and its controller remain as
narrow historical/evidence boundaries and are not reused for engine execution.

A separate, narrower v0.1 preparation request and event vocabulary now binds an
approval path, the independently recorded complete approval SHA-256, current
config hash, approved plan fingerprint, run ID, exact destination, and
`engine_execution_authorized: false`. Its ledger requires the complete
`verify_request`, `prepare_approved`, `verify_prepared_run` sequence and
cross-checks the nested approved-preparation evidence before accepting
`prepared_not_executed`. See the
[approval-bound preparation worker](REFERENCE_PREPARATION_WORKER.md).

This preparation harness does not modify the frozen nonnumerical request,
protocol, controller, or executable. It is now packaged as its own fourth
sibling and inventoried by freeze-evidence v0.3. The build exercises the exact
five-event preparation-only lifecycle with an external approval; frozen
preparation hard-parent-death behavior is checked by a separate mandatory
[pre-request evidence gate](FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md).

A separate source-level
[preparation parent controller](REFERENCE_PREPARATION_CONTROLLER.md) now assigns
this new child to a Windows kill-on-close Job before request delivery, bounds
its transport and runtime, reconciles the exact five-event lifecycle and exit
code, and independently verifies the published prepared run. It remains a
preparation-only boundary; the newer execution controller does not reuse its
approval as engine authorization.

Its real source-worker Job-assignment seam additionally has
[hard-parent-death evidence](REFERENCE_PREPARATION_PARENT_DEATH.md) using a
suspended child and immediate controller hard exit before request delivery.
That audit does not extend the protocol into execution or recovery.

The original frozen executable consumer remains deliberately nonnumerical: it verifies the
request across a real stdio child-process boundary and always emits
`stopped_before_prepare`. See
[the reference worker pipe harness](REFERENCE_WORKER_HARNESS.md).
Its parent-side contract is documented in
[the reference harness controller](REFERENCE_HARNESS_CONTROLLER.md).
