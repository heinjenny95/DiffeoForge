# Source preparation-worker hard-parent-death evidence

Status: **Windows Job-driven termination proved before request delivery**

This audit tests the real source
`diffeoforge.desktop.reference_preparation_worker_harness` through the real
[preparation parent controller](REFERENCE_PREPARATION_CONTROLLER.md). It proves
one narrow claim: after the worker is assigned to the controller's Windows
kill-on-close Job, immediate hard controller death cannot orphan that worker.

## Deterministic audit sequence

The audit requires an existing exact preparation-only approval, current config,
and independently recorded approval SHA-256:

```powershell
python tools/audit_reference_preparation_parent_death.py `
  review/pilot-001-approval.json atlas.yaml `
  --expect-request-sha256 THE_INDEPENDENTLY_RECORDED_REQUEST_SHA256
```

The outer audit process first rebuilds and verifies the complete approval-bound
request and requires both destination and matching private-stage prefix to be
absent. It then launches an isolated controller child. Only inside that child:

1. the real controller request is verified again;
2. the real preparation worker command is created with Windows
   `CREATE_SUSPENDED`;
3. the real `WindowsKillOnCloseJob` assigns that suspended process;
4. the audit Job wrapper durably writes the worker PID; and
5. the controller calls `os._exit(73)` immediately from the completed assignment.

Suspension is essential. The worker cannot read stdin, observe pipe EOF, emit an
event, prepare a run, or exit normally before the parent dies. Therefore a
stopped PID after controller exit is Job-driven termination evidence rather
than a fast-harness or cooperative-cleanup result.

The independent outer process requires exact controller exit code 73, reads the
recorded PID, and observes bounded process termination. It then rechecks that no
request was delivered, destination or private stage appeared, approval and
config bytes remained unchanged, and engine execution did not start.

## Versioned evidence

The sole ASCII-safe stdout document is validated against
`reference-preparation-parent-death-evidence-v0.1.json`. It binds:

- status and Windows platform;
- controller exit code and completed Job assignment;
- suspended-worker and bounded-stop observations;
- `request_delivered: false`;
- exact destination with `destination_exists: false`;
- `private_stage_count: 0`;
- approval SHA-256 and approved plan fingerprint;
- exact Python executable and real worker module;
- twelve ordered checks; and
- `engine_execution_started: false` plus the scientific boundary.

Malformed evidence cannot be printed as success because schema validation runs
before stdout publication. Operational failure prints a concise error on stderr
and exits with code 2.

## Boundary

This is source-worker Windows evidence. It does not change or validate the
frozen desktop bundle, installer inventory, or existing frozen nonnumerical
worker evidence. It does not claim portable parent-death behavior.

The worker is killed before request delivery, so this audit deliberately does
not model a crash after private staging begins. Such a crash can preserve a
`.diffeoforge-preparing-*` directory and requires a separate observational
discovery and user-approved reconciliation contract. This audit does not start,
interrupt, or validate Docker or Deformetrica; prove recovery; validate
scientific parameters; establish numerical equivalence or convergence; or
support biological interpretation.
