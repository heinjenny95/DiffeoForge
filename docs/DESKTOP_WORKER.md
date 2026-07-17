# Versioned desktop worker protocol

Status: **implemented source-level Modern CPU transport; not yet connected to GUI controls**

Tracked by [engineering issue #79](https://github.com/heinjenny95/DiffeoForge/issues/79).

## Purpose and boundary

Numerical work must not run in the Qt event loop. DiffeoForge therefore starts
the Modern CPU workflow in a separate process and exchanges newline-delimited
JSON over standard input and output. The protocol modules import neither Qt nor
the numerical engine until a validated request is ready to execute.

The worker reuses the existing `run_modern_workflow` service and embeds its
strict `modern-progress-v0.1` dictionaries unchanged. It does not implement a
second optimizer, estimate percent complete, invent an ETA, or infer resource
requirements.

## Transport contracts

The parent starts exactly one child process:

```text
python -m diffeoforge.desktop.worker
```

Command-line arguments are refused. The first input line must satisfy
`desktop-worker-request-v0.1.json`. Later nonblank input lines are control
commands satisfying `desktop-worker-command-v0.1.json`. Every output line
satisfies `desktop-worker-event-v0.1.json`.

A request binds one explicit Modern configuration and one previously
nonexistent destination to:

- a short request identifier;
- the `modern_cpu` engine identifier;
- absolute configuration and destination paths; and
- the SHA-256 of the reviewed configuration bytes.

The worker rehashes the configuration immediately before launch and refuses a
changed file or an existing destination. This catches edits between desktop
review and compute rather than silently running different parameters.

The event sequence begins at zero and contains:

- `started`: accepted engine, configuration hash, destination, and cancellation
  mode;
- `progress`: one unchanged, separately schema-validated Modern progress event;
- `completed`: verified destination, manifest hash, subject count, and bundle path;
- `cancelled`: explicit unpublished and nonresumable state; or
- `failed`: error type/message and whether the destination exists.

Exit code zero is reserved for verified completion. Cooperative cancellation
returns 130. A failure after a valid request returns 1. An invalid or missing
initial request returns 2 and writes a diagnostic to standard error because no
request identifier is trustworthy enough for an event envelope.

## Cancellation and atomic publication

The only v0.1 parent command is `cancel`. It must carry the active request
identifier. The reader thread records the request immediately; the compute
thread observes it at declared safe points between workflow stages and before
and after optimizer objective/gradient evaluations. Cancellation is therefore
cooperative, not a force-kill guarantee.

Before publication, all work lives in a hidden private temporary directory.
At a cancellation safe point the Modern workflow removes that directory and
does not create the destination. The terminal event records `published: false`
and `resumable: false`. The current Modern engine has no checkpoint contract,
so a cancelled run must be restarted from its reviewed configuration.

The final publication is one atomic directory rename after full workflow
verification. If cancellation arrives after the last safe point and the rename
has already won the race, verified completion wins; the worker never labels an
already published run as cancelled.

This is distinct from the external Deformetrica reference lifecycle, whose
inventoried checkpoints can create immutable successor runs. The desktop must
not present that reference capability as Modern-engine resume support.

## Parent implementation requirements

A desktop controller must:

1. create the request only after parameter/workload review;
2. keep standard input open while compute is active;
3. read standard output and standard error without blocking either pipe;
4. reject unknown versions, skipped/duplicate event sequences, and malformed
   nested progress;
5. send at most one matching cancellation command;
6. wait for the process and reconcile the terminal event with its exit code;
7. independently verify the published workflow before showing success; and
8. retain failure diagnostics without treating a partial directory as a result.

GUI start/cancel controls, crash reconciliation, checkpoint/recovery,
reference-engine process supervision, and result inspection are later slices.
The protocol is intentionally usable and testable before those controls exist.

## Verification evidence

Automated tests cover strict schema composition, deep event immutability,
configuration hash binding, Qt/numerical-engine-independent protocol import,
real subprocess completion, real subprocess cancellation, malformed commands,
destination nonpublication, and private temporary-directory cleanup on both
Windows and Ubuntu Modern-engine CI.
