# Frozen reference-worker parent-death evidence

Status: **Windows engineering containment evidence; no reference computation**

The Windows evidence builder includes a separate hard-parent-death audit for
`DiffeoForgeReferenceWorker.exe`. It complements the normal frozen protocol
smoke: the protocol smoke proves that the executable can consume the reviewed
request and emit the exact nonnumerical lifecycle, while this audit proves that
the contained executable cannot remain orphaned when its controller disappears.

## Audit sequence

`tools/audit_frozen_reference_parent_death.py` starts a short-lived Python
controller child. That child uses the real `ReferenceHarnessController` and
real `WindowsKillOnCloseJob`, but intercepts two precise process-boundary
operations:

1. the frozen worker is created with the Win32 `CREATE_SUSPENDED` flag;
2. the normal controller creates its Job Object and assigns that process;
3. only after successful assignment, a wrapper durably records the worker PID;
4. the controller process calls `os._exit(73)`, bypassing Python cleanup;
5. the outer auditor requires exit code 73 and observes that the recorded worker
   PID stops within a finite deadline.

Starting the worker suspended matters. It cannot read pipe EOF, execute harness
logic, or exit normally before observation. Therefore termination after the
controller's hard exit is evidence for the Job handle's
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` boundary, rather than an accidental clean
worker shutdown. Any timeout, missing PID handshake, different controller exit,
live worker, pre-existing destination, or created destination fails closed. A
still-live worker is terminated during audit cleanup before an error is returned.

The machine-readable report is ASCII-safe JSON so a non-ASCII Windows path does
not depend on the active console code page.

## Build gate

`distribution/windows/build-evidence.ps1` runs, in order:

1. the frozen GUI smoke;
2. the optional frozen Modern numerical smoke when supplied;
3. the mandatory frozen nonnumerical reference protocol smoke;
4. the mandatory frozen reference hard-parent-death audit;
5. the mandatory frozen approval-bound preparation worker/controller smoke;
6. v0.3 evidence creation and exact-inventory verification.

The manifest is not written if any mandatory reference-boundary smoke or audit
fails.

## Boundary

This proves termination of one suspended frozen reference-worker process after
hard death of the controller that owns its Windows Job handle. It does not prove
reference run preparation, descendant-engine containment, cancellation,
checkpointing, crash reconciliation, recovery after interruption, power-loss
behavior, Deformetrica execution, numerical validity, or clean-machine
installation. Those require separate lifecycle and release evidence.
