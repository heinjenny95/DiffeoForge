# Frozen approval-bound reference preparation worker

Status: **Windows developer-machine engineering evidence; disabled in the GUI**

The evidence-only Windows one-directory bundle contains a dedicated
`DiffeoForgeReferencePreparationWorker.exe`. It is the frozen entry point for
the same narrow harness used in source mode and is deliberately distinct from:

- `DiffeoForge.exe`, the windowed parent application;
- `DiffeoForgeWorker.exe`, the Modern numerical worker; and
- `DiffeoForgeReferenceWorker.exe`, the nonnumerical
  `stopped_before_prepare` harness.

The separation prevents a nonmutating reference diagnostic from silently
acquiring preparation authority and prevents preparation from acquiring engine
execution authority.

## Frozen command resolution

`ReferencePreparationWorkerController` uses the Python module entry point in a
source process. When `sys.frozen` is true, it resolves only the exact sibling
basename `DiffeoForgeReferencePreparationWorker` beside `sys.executable`, with
the platform executable suffix. The request, five-event protocol, bounds,
Windows Job assignment, exit-code reconciliation, and independent prepared-run
verification are identical in both modes.

## Mandatory build smoke

`distribution/windows/build-evidence.ps1` requires three explicit inputs:

- a pre-existing preparation-only approval JSON;
- the current exact reference config bound by that approval; and
- an independently recorded SHA-256 of the complete approval file.

The build does not generate approval or derive the external hash. The approved
destination must be absent. Before the successful smoke, the build uses the
same authorization inputs in a mandatory hard-parent-death audit of the real
frozen sibling. That audit must terminate the suspended worker before request
delivery and leave the destination absent. The smoke tool then constructs and prevalidates the
immutable child request, launches the frozen executable through the production
parent controller, and accepts only:

1. `accepted`;
2. phase `verify_request`;
3. phase `prepare_approved`;
4. phase `verify_prepared_run`; and
5. terminal `prepared_not_executed` with exit code 0.

It also requires unchanged approval/config bytes, a present verified
destination, exactly five events, and `engine_execution_started: false`. Any
failure prevents freeze-evidence creation. The successful smoke intentionally
leaves the immutable prepared run as auditable evidence; it never deletes or
executes it.

## Inventory version

New exact-file evidence uses `desktop-freeze-evidence-v0.3.json` and requires
all four sibling executables. Verification dispatches strictly by the recorded
schema version: genuine v0.1 two-entry-point and v0.2 three-entry-point
manifests remain readable, but neither is upgraded or interpreted as v0.3.

## Boundary

This proves one approval-bound, preparation-only operation through the real
frozen stdio and parent-controller boundary on the recorded Windows developer
host. It is not an installer, clean-machine, signing, antivirus, SBOM, license,
recovery after preparation begins, engine-containment, Deformetrica-execution,
numerical, biological, or 300-specimen validation result. Source and frozen
workers now have separate pre-request hard-parent-death evidence. Neither proves
recovery or containment after preparation begins. The GUI remains disabled for
reference preparation. See
[frozen preparation-worker parent-death evidence](FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md).
