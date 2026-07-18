# Versioned desktop reference worker protocol

Status: **transport contract with nonnumerical harness consumer; no engine launch**

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
event envelopes with a contiguous zero-based sequence and one of three kinds:

- `accepted`: exact engine, config hash, destination, and the explicit
  `phase_dependent` cancellation contract;
- `phase`: a strictly advancing lifecycle phase from request verification
  through result verification; or
- `terminal`: one of `completed`, `stopped_before_prepare`,
  `prepared_not_executed`, `interrupted`, or `failed` with destination and
  result-hash evidence appropriate to that outcome.

## Parent-side ledger

The Qt-independent ledger is constructed from the immutable prelaunch request
and binds acceptance to its request ID, configuration hash, and exact
destination. It rejects a different request ID, hash, destination, sequence gaps,
repeated acceptance, phase repetition or regression, non-failure terminal data
without acceptance, a completed outcome before `verify_result`, stop outcomes
that contradict the observed phase, post-terminal data, and a stream ending
without a terminal event.

The schema also couples outcome to evidence. Completed and interrupted outcomes
require an existing destination and a 64-character result SHA-256. A stop before
preparation requires no destination or result. A prepared-but-unexecuted stop
requires the destination but no result hash.

## Current boundary

The executable consumer remains deliberately restricted to the nonnumerical
harness. Its parent controller provides a bounded pipe reader, timeout, Windows
Job containment and exact `stopped_before_prepare` reconciliation, but supplies
no signal delivery, run preparation, Deformetrica start, result publication,
recovery, resume, or GUI enablement. Later code must preserve this request and
protocol boundary and prove terminal result verification before the reference
button can be enabled.

A shared-core approval-aware preparation service now exists outside this worker
transport and proves exact private staging plus pristine prepared state. The
current harness does not import or call it. A future request version must bind
the approval path and complete request SHA-256 and must preserve the existing
parent ledger's `prepared_not_executed` boundary before this mutation can cross
the frozen worker pipe. See
[approved reference preparation](REFERENCE_APPROVED_PREPARATION.md).

The first executable consumer is deliberately nonnumerical: it verifies the
request across a real stdio child-process boundary and always emits
`stopped_before_prepare`. See
[the reference worker pipe harness](REFERENCE_WORKER_HARNESS.md).
Its parent-side contract is documented in
[the reference harness controller](REFERENCE_HARNESS_CONTROLLER.md).
