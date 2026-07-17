# Versioned desktop worker protocol

Status: **implemented Modern CPU transport, verified parent controller,
source GUI integration, and native Windows parent-death process containment**

Tracked by [engineering issue #79](https://github.com/heinjenny95/DiffeoForge/issues/79)
and [parent-controller issue #81](https://github.com/heinjenny95/DiffeoForge/issues/81),
with GUI integration tracked by
[engineering issue #83](https://github.com/heinjenny95/DiffeoForge/issues/83) and
parent-death containment by
[engineering issue #89](https://github.com/heinjenny95/DiffeoForge/issues/89).

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

## Verified parent controller

`DesktopWorkerController` implements the parent side without importing Qt. It:

1. creates the request only after parameter/workload review;
2. keeps standard input open while compute is active;
3. reads standard output and standard error without blocking either pipe;
4. rejects unknown versions, skipped/duplicate event sequences, and malformed
   nested progress;
5. sends at most one matching cancellation command;
6. waits for the process and reconciles the terminal event with its exit code;
7. independently verifies the published workflow before showing success; and
8. retains failure diagnostics without treating a partial directory as a result.

Every event must match the reviewed request identifier and destination. The
`started` event must additionally reproduce its engine and configuration hash.
Sequences begin at zero, remain contiguous, follow the declared lifecycle, and
contain exactly one terminal event. The controller reconciles `completed`,
`cancelled`, and `failed` with exit codes 0, 130, and 1 respectively. A
completed event is accepted only after independently re-verifying the workflow
and cross-checking manifest SHA-256, subject count, and bundle path.

A cancellation requested during process creation is queued until the complete
launch request has been written. This prevents a fast GUI click from becoming
the first input line and being misread as the worker request. Repeated clicks
do not emit duplicate commands.

Standard error is drained concurrently so a verbose dependency cannot block
the JSON protocol. Diagnostics are retained up to 65,536 characters and then
explicitly marked truncated. After a terminal event the parent closes the
command pipe and allows five seconds for a clean process exit before stopping a
nonconforming process. Started, progress, and terminal events remain raw
transport observations; only a successful controller return is reconciled
completion.

## Windows lifecycle hardening

Every Windows controller now creates a dedicated unnamed Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` before it launches a worker. The child is
assigned before the reviewed request line is written. The controller retains
the only Job handle throughout supervision and closes it on every exit. If the
GUI process crashes or is forcibly terminated, Windows closes that handle and
terminates the associated worker process tree. Job creation, configuration, or
assignment failure is fail-closed: the uncontained child is stopped and no
request is sent.

There is necessarily a short interval between `Popen` creating the child and
`AssignProcessToJobObject` returning. The production worker provides a second,
cross-platform boundary for that interval: EOF on its command pipe means the
parent disappeared and requests cooperative cancellation at the next declared
safe point. It emits no misleading terminal event to a disconnected parent. If
atomic publication already won the final race, the verified result may remain;
otherwise the normal exception path removes private temporary work.

The Job Object behavior follows Microsoft's documented assignment and
kill-on-last-handle-close contracts. Nested Job Objects require Windows 8 or
Windows Server 2012 or newer, consistent with the project's current Windows 11
target. A native hard-parent-exit test launches a real controller parent, waits
until its child is contained, calls `os._exit`, and verifies that the child PID
disappears without a destination.

This does not make a power-loss recovery claim. A force kill can interrupt the
worker before Python cleanup executes and may leave a private
`.NAME.tmp-UUID` directory. Modern runs now hold a versioned marker and native
file lease while that directory is active. The shared read-only discovery
service and `modern-private-status` command classify exact-destination
candidates without following links or changing files. Explicit user-approved
reconciliation remains a separate slice; DiffeoForge does not automatically
delete private state or present it as a result. See
[the private-run discovery contract](PRIVATE_RUN_DISCOVERY.md).

Primary platform references:

- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Microsoft: AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)
- [Microsoft: SetInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject)

The worker imports the Modern numerical runtime before starting its blocking
command-reader thread. A real Windows parent-process test found that importing
PyTorch concurrently with the already blocked pipe reader could stall before
the first workflow event. The dedicated process therefore establishes the
runtime first, emits `started`, and only then begins cooperative command input.
A cancel command sent while the runtime loads remains buffered by the operating
system and is observed before substantive workflow work.

After `run_worker` has emitted and flushed its terminal event, the module entry
point exits the dedicated process directly. This deliberately bypasses Python
interpreter shutdown waiting on a daemon reader whose parent may keep stdin
open. Scientific cleanup and atomic publication have already completed inside
`run_worker`; operating-system process teardown then releases the isolated
runtime. Direct in-process tests continue to call and return from `run_worker`
normally.

## Source GUI integration

Desktop step 3 now places the synchronous controller in a Qt thread-pool task
and forwards its already validated event objects through Qt signals. It does
not parse a second event format or call numerical services in the GUI process.
The complete review captures the configuration SHA-256; launch is refused if
the file differs before or during request creation.

The screen displays the exact workflow phase/status/message, completed-stage
count, and committed optimizer decision fields. It does not derive an ETA,
runtime forecast, peak-memory claim, or percent-complete value. A cancel click
is idempotent and remains queueable even before the Qt task begins or while the
child process is being created. Success appears only after the controller has
reconciled the process and independently verified the published result.

A normal window-close request while a GUI-launched worker is active requests
cooperative cancellation and is deferred until a reconciled worker outcome.
Hard Windows parent termination now stops the contained worker process tree,
while command-pipe EOF supplies cooperative fallback on every platform. Power
loss and abandoned-private-directory reconciliation, checkpoint/recovery, and
reference-engine process supervision remain later evidence gates.

## Verification evidence

Automated tests cover strict schema composition, deep event immutability,
configuration hash binding, Qt/numerical-engine-independent protocol and
controller imports, real subprocess completion and cancellation, malformed
commands, adversarial identities/sequences/lifecycles/exit codes, bounded
stderr, independent result verification, destination nonpublication, and
private temporary-directory cleanup on both Windows and Ubuntu Modern-engine
CI.
