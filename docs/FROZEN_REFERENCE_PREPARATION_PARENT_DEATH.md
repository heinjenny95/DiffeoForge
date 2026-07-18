# Frozen preparation-worker parent-death evidence

Status: **Windows developer-machine engineering evidence; GUI disabled**

The evidence-only Windows build includes a dedicated hard-parent-death audit
for `DiffeoForgeReferencePreparationWorker.exe`. This closes the narrow gap
between source-worker containment and the actual frozen, approval-bound
preparation sibling without granting engine or GUI authority.

## Exact audit seam

`tools/audit_frozen_reference_preparation_parent_death.py` prevalidates an
external preparation-only approval, its full-file SHA-256, and the current
config. It requires the approved destination and every matching private stage
to be absent. A short-lived controller process then:

1. uses the production `ReferencePreparationWorkerController`;
2. creates the exact frozen sibling executable with `CREATE_SUSPENDED`;
3. assigns its real process handle to a real Windows kill-on-close Job;
4. durably publishes the worker PID only after that assignment succeeds; and
5. calls `os._exit(73)` from the assignment seam, before the controller can
   resume the worker or transmit the immutable request.

An independent outer process observes exit code 73 and the recorded PID. It
requires the worker to terminate within a bounded deadline, then checks that
the destination and private stage are still absent and that the approval and
config bytes are unchanged. The worker was never resumed, so no protocol event
or engine launch can have occurred.

## Versioned evidence

The JSON summary is validated against
`frozen-reference-preparation-parent-death-evidence-v0.1.json`. The schema
fixes the executable basename, controller exit code, Job assignment, suspended
start, worker termination, zero request delivery, zero destination/private
stage mutation, unchanged authorization inputs, and
`engine_execution_started: false`.

The clean Windows builder runs this gate after the nonmutating frozen reference
audit and before the successful frozen preparation smoke. That ordering is
intentional: the death audit must leave the approved destination absent; only
the following fully supervised smoke may publish it.

## Boundary

This proves frozen-process containment only at the pre-request seam on the
recorded Windows developer host. It does not prove termination after the
worker is resumed or preparation starts, crash-stage reconciliation, recovery,
cancellation, Deformetrica process-tree containment, engine interruption,
installer behavior, clean-machine execution, numerical equivalence,
registration quality, convergence, scientific validity, or biological
interpretation. The GUI remains disabled for reference preparation.
