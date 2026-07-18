# Approval-bound reference preparation parent controller

Status: **source child contained and independently verified; no engine launch**

`ReferencePreparationWorkerController` is the Qt-independent parent for the
[approval-bound reference preparation worker](REFERENCE_PREPARATION_WORKER.md).
It is single-use and accepts only an already constructed
`DesktopReferencePreparationRequest`. Success means that one exact approved run
was atomically published, independently reverified by the parent, and left in
`prepared_not_executed`. It never authorizes or starts the reference engine.

## Before process launch

The controller repeats the request's complete verification before creating a
child. Approval and config bytes, external approval SHA-256, embedded plan,
fresh current plan, mesh inventory, run ID, destination, and destination
absence must still agree. A stale request fails without launching a process.

The default command deliberately resolves only the source module. A frozen
desktop process fails explicitly because no approved preparation-worker sibling
has been added to the bundle yet; it cannot silently reuse the frozen
nonnumerical worker.

## Containment and bounded transport

On Windows, the controller creates a kill-on-close Job Object and assigns the
child before sending any reviewed request byte. If launch or assignment fails,
the process is stopped and no request is delivered. The request is serialized
as ASCII-safe JSON, including escaped Unicode paths, written as one LF-terminated
line, flushed, and followed by stdin close.

The parent enforces:

- a finite 600-second default supervision timeout;
- at most five stdout events;
- a 256 KiB limit for each stdout line;
- 64 KiB retained stderr with an explicit truncation marker;
- strict UTF-8 JSON with unique object keys and finite values;
- contiguous request-bound event reconciliation; and
- exact terminal-outcome/exit-code agreement.

Timeout or protocol failure stops the child. The worker currently starts no
descendant process. A dedicated
[Windows hard-parent-death audit](REFERENCE_PREPARATION_PARENT_DEATH.md) now
proves Job-driven termination of the real source worker created suspended and
killed before request delivery. Frozen-bundle and portable process-tree
containment remain later gates.

## Accepted success

The only successful stream is:

1. `accepted`;
2. `verify_request`;
3. `prepare_approved`;
4. `verify_prepared_run`;
5. terminal `prepared_not_executed` with exit code 0.

The event ledger first cross-checks request identity, hashes, plan, destination,
manifest, and nested preparation evidence. The controller then independently
invokes `verify_prepared_run` on the published destination and hashes
`manifest.json` itself. It additionally binds manifest run ID, copied source
config SHA-256, and backend ID to the original request. Only then does state
become `verified`.

A schema-valid `failed` terminal requires exit code 1 and is preserved in a
dedicated exception. Malformed or incomplete transport cannot masquerade as a
domain failure or success.

## Preservation boundary

The controller never deletes a published destination. If parent reverification
fails after atomic publication, it reports failure and leaves the prepared run
available for separate inspection. Likewise, a timeout or hard termination can
leave a hidden `.diffeoforge-preparing-*` directory. This controller preserves
that private state; it provides no discovery, deletion, promotion, retry,
resume, or reconciliation action.

This is intentional evidence preservation, not a claim that every preserved
candidate is valid. A later observational discovery contract and explicit
user-approved reconciliation workflow must classify it before any mutation.

## Current boundary

The controller is source-level and has no Qt dependency. It is not wired into
the GUI, frozen Windows bundle, installer, or release evidence. It has no cancel
channel and never reaches Docker, Deformetrica, execution, checkpoint, resume,
or result collection. It does not validate scientific parameters, mesh
homology, convergence, registration quality, numerical equivalence, or
biological interpretation.
