# Approval-bound reference preparation worker

Status: **real child-process preparation; verified stop before engine execution**

This source-level harness is the first reference worker allowed to mutate a run
destination. It consumes one exact, independently hash-bound
[preparation-only approval](REFERENCE_PREPARATION_APPROVAL.md), invokes the
shared [atomic approved-preparation service](REFERENCE_APPROVED_PREPARATION.md),
reverifies the published run, and terminates with
`prepared_not_executed`. It never starts Docker, Deformetrica, or another
engine process.

It is deliberately separate from the frozen nonnumerical v0.1 worker. That
older executable and its `stopped_before_prepare` evidence remain unchanged.

## Request contract

Schema `desktop-reference-preparation-request-v0.1.json` fixes:

- operation `prepare_approved_only` and engine `deformetrica_reference`;
- absolute approval, current-config, and destination paths;
- the independently recorded SHA-256 of the complete approval request;
- the SHA-256 of the current configuration;
- the approved plan's canonical fingerprint, run ID, and exact destination;
- `engine_execution_authorized: false`.

The builder strict-loads the saved approval, checks its external hash, derives
the remaining values from the embedded plan, and immediately performs the full
current-state verification. The child repeats that verification before
mutation. Any changed approval, config, mesh, generated artifact, plan value,
run ID, or destination fails closed.

The module accepts exactly one LF-terminated JSON request line on stdin. Extra
input, duplicate JSON keys, relative paths, unsupported fields, or command-line
arguments are rejected.

## Event contract

Schema `desktop-reference-preparation-worker-event-v0.1.json` defines a
contiguous zero-based JSON Lines stream:

1. `accepted`, echoing the exact approval hash, config hash, plan fingerprint,
   run ID, destination, and non-execution boundary;
2. phase `verify_request`;
3. phase `prepare_approved`;
4. phase `verify_prepared_run`;
5. terminal `prepared_not_executed` with the prepared manifest hash and the
   complete schema-valid approved-preparation evidence.

The parent-side ledger requires every phase exactly once and in order. It
cross-checks the terminal envelope and nested evidence against the original
request, including destination, approval hash, plan fingerprint, manifest hash,
and `engine_execution_started: false`. A runtime failure may terminate after
any completed phase with outcome `failed`; it cannot claim preparation
evidence.

Exit code 0 means the complete success stream was emitted. Exit code 1 means a
schema-valid runtime failure terminal was emitted. Exit code 2 means the input
transport itself was invalid, so no trusted request identity existed and no
event stream is emitted.

## Atomicity and execution boundary

The worker delegates mutation to the shared service: private exact staging,
approval reread immediately before publication, platform-specific
non-replacing atomic publication on Windows and Linux, and complete prepared-run
verification. On success the destination contains the immutable manifest and
protected inputs, exactly one `prepared` lifecycle event, and an empty output
directory. There is no `result.json`, Deformetrica log, or engine execution
event.

A failure after atomic publication preserves the valid prepared destination and
reports `destination_exists: true`; it does not silently delete evidence. A
failure before publication leaves the final destination absent.

## Current boundary

Run the source harness only as a protocol child:

```powershell
python -m diffeoforge.desktop.reference_preparation_worker_harness
```

The source harness now has a separate Qt-independent
[bounded parent controller](REFERENCE_PREPARATION_CONTROLLER.md). On Windows the
controller assigns it to a kill-on-close Job before delivering the request and
accepts success only after independent prepared-run verification. The harness
is still not wired into the GUI, an installer, or the frozen Windows bundle. It
has no cancel channel and no reference-engine process tree. In particular, this
boundary proves approval-bound preparation across a real pipe; it does not
estimate an atlas, validate scientific parameters, establish approver identity,
or authorize execution.
