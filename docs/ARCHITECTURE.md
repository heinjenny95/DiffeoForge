# Architecture

Status: **draft**

## Layered design

```text
GUI and CLI
    |
Application service (validate, prepare, execute, run, recover, resume, status, report)
    |
Versioned configuration and run-manifest contracts
    |
Backend interface
    +-- Deformetrica reference backend
    +-- Modern LDDMM backend (future, validation required)
```

The GUI must not implement separate scientific behavior. It edits the same
configuration schema and calls the same application service as the CLI.

## Configuration as a public contract

The user-facing YAML is validated against a versioned JSON Schema. This allows
the CLI, GUI, documentation, and future workflow integrations to share field
names, types, allowed values, and descriptions.

The YAML is not passed directly to a numerical engine. A backend adapter
translates the validated configuration into engine-specific input and records
the fully effective configuration in the run directory.

## Prepared-run boundary

Preparation is atomic: files are first assembled in a temporary directory and
renamed to the final run ID only after geometry inspection, input copying, XML
generation, hashing, and manifest-schema validation all succeed. Preparation
never overwrites an existing run ID.

`manifest.json` and its SHA-256 sidecar describe all evidence known before
execution. Staged input, source/effective configuration, and generated XML are
protected by hashes. `events.jsonl` records the append-only lifecycle.
Execution verifies this evidence and requires an empty output directory before
starting the backend exactly once. `result.json`, `logs/convergence.csv`, and
`output-inventory.json` record the terminal outcome without rewriting the
prepared manifest.

`result-report.html` is a derived, regenerable view of those evidence files.
It is not a substitute for them and is not included in the numerical output
inventory. Report generation revalidates the prepared-manifest digest and
checks consistency among the terminal event, result, convergence-row count,
and output inventory. The report is self-contained and performs no network
requests.

## Interruption and successor boundary

A clean keyboard interrupt is finalized as a terminal `interrupted` state with
partial logs, convergence history, output inventory, and checkpoint evidence. An
unclean `started` state can be finalized only by an explicit recovery operation
after the caller confirms that the numerical process has stopped.

Resume does not reopen the source run. It atomically prepares an immutable
successor containing a versioned `resume/resume.json` provenance record and a
protected copy of the source checkpoint. The execution copy is placed under the
new run's `output/` only after protected-artifact and environment verification.
The adapter treats the checkpoint as opaque bytes; only the pinned backend may
deserialize it.

## Backend boundary

The backend contract is defined by operations comparable to:

```text
capabilities()
validate(config, dataset)
prepare(config, dataset, run_directory)
execute(run_directory, progress_callback)
resume(run_directory, progress_callback)
collect(run_directory)
```

The interface is deliberately defined by observable behavior and artifacts,
not by Deformetrica's XML structure. The current reference adapter generates
three XML files and invokes an externally supplied Deformetrica 4.3.0
executable. A modern backend does not need to use XML or Python 3.8.

Dense PyTorch CPU/float64 is the inspectable modern correctness baseline
selected by ADR 0002. The experimental `modern-run` application service now
connects folder preflight, optional labelled-landmark Procrustes alignment,
deterministic initialization, full block optimization, and an immutable
atlas/PCA result bundle. Its outer run copies and hashes raw inputs, records
aligned copies and transformations when enabled, and verifies the nested
bundle before atomic publication.

The same application layer exposes a read-only `modern-plan` service before
compute. It inspects the resolved cohort and configuration, applies a versioned
exact all-pairs operation model, records the largest logical pair separately
from the largest configured dense matrix or blockwise execution tile, records
known tensor payloads and host observations, and publishes strict JSON plus
self-contained HTML. It deliberately does not cross the backend boundary into
runtime or peak-memory prediction.

`modern-run` now accepts a synchronous read-only progress observer. The
application service emits versioned workflow-stage events and translates the
dense optimizer's committed decision records without exposing rejected
line-search candidates as accepted progress. CLI output and the source-level
desktop worker protocol consume this same contract. The worker adds a strict
request/command/event envelope, configuration-hash binding, child-process
isolation, and nonpublishing cooperative cancellation. A Qt-independent parent
controller enforces identity, sequence, lifecycle, terminal/exit agreement,
bounded stderr capture, and independent completed-run verification before a
caller may accept success. Desktop step 3 runs that controller in a Qt worker
task, refuses a configuration whose bytes no longer match the completed review,
and transports the validated event objects through Qt signals without a second
scientific progress model. Counts describe completed stages and decisions, not
elapsed-time percentages or ETA.

Private Modern computation is now bound to a versioned marker and an exclusive
process lease. Exact-destination discovery reports held leases as active and
released valid leases as abandoned; missing, malformed, indeterminate, and
symbolic-link state fails closed. Marker and lease are removed before artifact
inventory and atomic publication. The shared service and
`modern-private-status` command are observational only and implement no
deletion, rename, resume, or result promotion. See
[the private-run discovery contract](PRIVATE_RUN_DISCOVERY.md).

Desktop step 3 consumes that same Qt-independent readiness object. It binds the
reviewed configuration hash to the exact worker request, displays the discovery
status and candidate evidence, and repeats the binding plus discovery directly
before constructing the controller. The GUI never supplies a weaker alternate
classification and does not expose a destructive recovery action.

The external reference path has a separate observational readiness seam in
desktop step 2. It parses the exact bytes captured by the completed review,
extracts the configured container engine and image, and runs the existing
read-only doctor service outside the GUI thread. A second hash check discards
the report if the configuration changes during observation. Passing this check
does not prepare or launch Deformetrica and does not weaken the separate open
gate for reference-process supervision. See
[the desktop reference-readiness contract](REFERENCE_DESKTOP_READINESS.md).

A separate Qt-independent reference prelaunch seam now binds that matching
review/readiness pair to a versioned request containing the exact config hash,
container engine/image, normalized run ID, and resolved absolute destination.
The request is round-trip schema validated and repeatably rechecks bytes,
launcher settings, output resolution, and destination nonexistence. It performs
no preparation or execution and remains only an input contract for a future
contained supervisor. See
[the desktop reference-prelaunch contract](REFERENCE_PRELAUNCH.md).

Reference worker transport now has a separate versioned event vocabulary and
parent-side ledger because its phase-dependent stop states cannot reuse the
Modern worker's nonpublishing cancellation claim. The ledger distinguishes no
destination, an immutable prepared destination, and a terminal interrupted run,
while rejecting sequence, phase, terminal, and evidence contradictions. This is
still a non-executing protocol seam; see
[the reference worker protocol](REFERENCE_WORKER_PROTOCOL.md).

A deliberately nonnumerical reference worker harness now exercises that request
and event vocabulary over a real child-process stdio boundary. It revalidates
the exact request in the child and terminates with `stopped_before_prepare`;
tests prove the project tree remains byte-identical. It is not the production
worker and creates no descendant process, run directory, or engine artifact.

A dedicated Qt-independent parent controller now launches only that harness. It
assigns the child to a Windows kill-on-close Job before sending the request,
enforces a finite timeout and bounded stdout/stderr, requires the exact
three-event harness lifecycle and matching exit code, and repeats the complete
request/destination verification after child success. This closes the
nonnumerical supervision seam but does not prepare a run, start the reference
engine, or enable GUI computation. See
[the reference harness controller](REFERENCE_HARNESS_CONTROLLER.md).

The Windows one-directory build freezes that same harness as a third sibling
entry point. Freeze-evidence schema v0.2 required the GUI, Modern worker, and
reference harness in the exact inventory, and the build exercises the frozen
harness through its controller before evidence is written. Verification retains
version-dispatched v0.1 and v0.2 compatibility without granting either legacy
artifact a newer evidence claim.

The clean Windows build additionally audits hard parent death at this exact
frozen boundary. It creates the reference worker suspended, lets the real
controller complete Job assignment, then terminates that controller without
cleanup and requires the worker PID to stop. Suspension prevents normal harness
exit or pipe EOF from masquerading as Job-driven containment. This is termination
evidence only, not crash recovery or reference execution; see
[the frozen reference parent-death evidence](FROZEN_REFERENCE_PARENT_DEATH.md).

Before any preparation mutation, a separate shared-core service can now derive a
strict v0.1 reference preparation plan for an explicit run ID. It inventories
and rechecks all input bytes, resolves the absent destination, renders the exact
effective YAML and three Deformetrica XML payloads in memory, and exposes every
future protected path/hash plus the command preview. The real atomic prepare path
uses the same byte renderer, and parity tests require its protected artifacts to
match the plan exactly. This is read-only transparency, not a prepared run or a
desktop execution permission; see
[the reference preparation plan](REFERENCE_PREPARATION_PLAN.md).

An optional deterministic HTML view is derived directly from that same validated
plan object. It owns no backend or preparation behavior, has no active content or
network dependency, and is published only to an explicitly selected absent path.
The unchanged JSON stdout remains the machine-readable contract.

A separate read-only verifier parses a saved plan under strict JSON rules,
revalidates its versioned schema, computes the canonical content fingerprint,
optionally binds an externally recorded fingerprint, and requires any supplied
HTML to equal deterministic regeneration byte-for-byte. Its own v0.1 evidence
schema reports saved-artifact consistency only; it deliberately does not reread
current mesh sources or reinterpret an old absent-destination observation as
current state. See
[saved reference preparation verification](REFERENCE_PREPARATION_VERIFICATION.md).

A separate deterministic v0.1 approval request binds explicit
preparation-only intent to one complete embedded plan and its reviewed canonical
fingerprint. Request creation freshly replans and fails on any mismatch; strict
verification can additionally replan against a current config and require the
destination to remain absent. The record fixes engine authorization to false,
has no identity/signature claim, and is not consumed by the existing prepare
path. A future atomic consumer must fresh-replan again immediately before
staging and must stop before execution. See
[reference preparation-only approval](REFERENCE_PREPARATION_APPROVAL.md).

The approval-aware preparation service adds the first intentionally mutating
consumer without weakening the execution boundary. It requires an external hash
of the complete request, freshly exact-matches the embedded plan, stages under a
private temporary directory, compares all plan-bound manifest and protected-byte
fields, and rereads the request immediately before publication. Windows uses a
non-replacing rename and Linux uses `renameat2(RENAME_NOREPLACE)` so a destination
appearing during staging is preserved. Only after schema-valid evidence exists
is the directory published; the service then invokes the full prepared-run
verifier and returns status `prepared_approved_reference_run_not_executed`. It
does not call the engine or alter the frozen worker harness. See
[approved reference preparation](REFERENCE_APPROVED_PREPARATION.md).

A distinct preparation worker now carries that exact authorization
across a real child-process pipe. Its immutable request binds the complete
approval hash, current config hash, approved plan fingerprint, run ID, and
destination while fixing engine authorization to false. Its separate event
ledger requires all three preparation phases in order and accepts
`prepared_not_executed` only when the nested preparation evidence, manifest,
destination, approval hash, and plan fingerprint agree. The worker performs no
engine launch. It intentionally leaves the frozen nonmutating worker untouched.
The evidence-only Windows build now adds it as a fourth sibling and v0.3 exact
inventory entry; an externally created, independently hash-bound approval must
complete the real frozen controller smoke before evidence is written. Before
that mutating smoke, the builder now hard-exits the real controller after Job
assignment and proves the suspended frozen preparation sibling terminates with
zero request delivery or filesystem mutation. Cancel semantics and GUI
enablement remain open. See
[the frozen preparation parent-death evidence](FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md).
See [the approval-bound preparation worker](REFERENCE_PREPARATION_WORKER.md).

Its distinct Qt-independent parent controller now prevalidates the request,
assigns the source or dedicated frozen child to a Windows kill-on-close Job before sending an
ASCII-safe request line, and bounds time, event count, line size, and stderr. It
accepts only the exact five-event lifecycle with exit code 0, then independently
verifies the prepared run and binds the observed manifest, run ID, copied config
hash, and backend to the request. Failure preserves any published destination
or private crash stage. The controller is not GUI-wired and performs no
deletion, reconciliation, cancellation, or execution. See
[the preparation parent controller](REFERENCE_PREPARATION_CONTROLLER.md).

The controller's Windows hard-parent-death seam now has a deterministic
source-worker audit. It creates the real preparation worker suspended, performs
the real kill-on-close Job assignment, durably records the PID, and hard-exits
the controller before request delivery. An independent process requires bounded
worker termination plus absent destination/private stage and schema-valid v0.1
evidence. This proves Job-driven termination at that exact pre-request boundary,
not frozen-bundle containment or crash recovery after staging begins. See
[the preparation parent-death evidence](REFERENCE_PREPARATION_PARENT_DEATH.md).

One approval-bound read-only reconciliation service now covers the state after
an uncertain preparation outcome. It external-hash-binds the complete approval,
freshly exact-matches the current plan even when the approved destination
exists, and twice observes only that destination plus exact private-stage
names. Real directories must have the exact approved surface and pass manifest,
protected-byte, prepared-lifecycle, and pristine-output verification; links are
never followed. The versioned report can identify a verified complete but
unpublished private stage, but it never deletes, publishes, resumes, repairs,
or executes one. See
[approval-bound preparation status](REFERENCE_PREPARATION_RECONCILIATION.md).

A separate saved-report verifier strict-loads one reconciliation artifact,
requires an external complete-file SHA-256, validates its schema and exact
deterministic serialization, and rereads it before returning versioned
verification evidence. It deliberately reads no current config, meshes,
approval, run path, process, container, or engine state. See
[saved status verification](REFERENCE_PREPARATION_RECONCILIATION_VERIFICATION.md).

Desktop step 2 consumes that report through a separate Qt-independent bounded
view model. It first binds the current config bytes to the completed desktop
review, delegates all reconciliation semantics to the shared core, and checks
the review binding again before returning. The background Qt task discards a
result if the approval path/hash or reviewed config binding changed while it
ran. The view exposes raw status/reason/hash evidence and never turns a clear
destination or verified private stage into preparation or publication
authority. A user may export the exact immutable, schema-valid report bytes to
one explicitly selected new JSON file; exclusive creation prevents overwrite,
and the GUI discloses the byte count, SHA-256, and private-path surface. See
[desktop reference preparation status](DESKTOP_REFERENCE_PREPARATION_STATUS.md).

Both setup routes can also pass their already selected template path to a
Qt-independent immutable preview model. The model reuses the strict VTK parser,
binds the source SHA-256 before and after loading, freezes vertices, triangles,
bounds, and sorted unique edges, and computes deterministic aspect-preserving
XY/XZ/YZ projections without rereading the file. A QPainter widget receives
only this model and draws at most the disclosed display-edge budget. This is a
native inspection seam, not a second QC service or an interactive 3D/landmark
system. See [the template-preview contract](TEMPLATE_PREVIEW.md).

Desktop step 4 consumes no alternate scientific model. A Qt-independent result
reviewer first invokes the complete outer Modern verifier, binds the unchanged
outer and nested manifest hashes, and reads only schema- and inventory-named
optimizer, PCA, deformation, and mesh-quality evidence. The Qt task exposes
bounded display values and the scientific boundaries recorded by those
manifests. Before a selected VTK, CSV, JSON, or SVG is handed to the operating
system, a second read-only task rechecks both manifest hashes and that artifact's
path containment, regular-file status, byte size, and SHA-256. This is an
auditable file handoff, not native rendering or biological interpretation.

The application layer also exposes an opt-in `modern-benchmark` service. The
user must declare a deterministic subject-prefix size. Each repeat runs one
configured dense or blockwise objective plus gradient in a fresh spawned CPU
process after declared warm-up evaluations, recording wall-clock nanoseconds
and 5 ms process-RSS samples. The strict report binds measurements to
config/input hashes, pairwise plan, and the same exact operation model as
`modern-plan`. Version 0.3 can replace standard with recompute only inside a
configured blockwise benchmark worker and records that benchmark-only choice;
version 0.4 can additionally carry explicit positive query/source tile sizes
across the spawn boundary for a configured blockwise base plan. The v0.4 report
separates source-declared and effective plans, and its worker, operation model,
semantic validator, and HTML all use the effective plan. Neither version
performs an automatic comparison, scaling extrapolation, or hardware verdict.

`modern-benchmark-design` sits immediately before measurement. Its immutable
v0.1 JSON/sidecar/HTML artifact binds the complete input inventory, reviewed
blockwise config, paired subject-prefix sizes, repeats, warm-ups, and a
versioned deterministic condition order. It contains no result fields and does
not execute the argument vectors. This separates prospective decisions from
later benchmark observations; execution, cross-config multi-size designs, and
analysis remain distinct evidence gates.

`modern-benchmark-study` is the corresponding execution service. Before work,
it regenerates the frozen design from the supplied config and current complete
input inventory, requiring exact equality. It executes conditions in their
stored order, verifies JSON/CSV/regenerated-HTML agreement for every v0.3 raw
report, tracks an atomic resumable prefix, and publishes a strict completion
manifest with artifact hashes. It never aggregates the observations. A
process-identity lock rejects concurrent writers; valid reports found after an
interruption are reconciled rather than overwritten.

The read-only `modern-benchmark-study-status` path applies the same design,
source-copy, frozen-prefix, raw-report, event-order, and lock inspection without
reconciling or writing. It distinguishes a recoverable report-ahead-of-state
crash from the unsafe inverse: state claiming a missing report is data loss or
tampering and stops both inspection and execution. A separate
`modern-benchmark-study-verify` entry point requires the complete state,
manifest sidecar, regenerated manifest, events, and every raw report.

Long study execution accepts a synchronous immutable progress observer. Strict
v0.1 events expose lifecycle status, exact completed/total condition counts,
and the current frozen condition identity. Start, resume, reconciliation,
interruption, completion, and already-complete paths are explicit. The CLI is
the first consumer; no event contains a percentage, elapsed-time fraction,
ETA, runtime forecast, or comparative result. Tests require callback presence
to leave all published evidence byte-identical.

The next multi-tile study is governed by
[ADR 0004](decisions/0004-prospective-multi-tile-matrix.md). It uses one hashed
base config plus explicit benchmark-only effective tile plans, not a bag of
hand-edited YAML files. The raw v0.4 report gate and separate matrix-design v0.1
gate feed a separate matrix-study run v0.2 service. It executes explicit tile
overrides in frozen order, preserves every raw v0.4 report, supports strict
prefix recovery, and publishes a tile-aware manifest. Progress v0.2 carries the
cell and effective plan without ETA. Separate commands and verifiers provide
explicit version dispatch; the existing v0.1 single-tile study artifacts and
service retain their exact meaning.

Below the application layer, the engine now contains an explicit blockwise
Gaussian primitive family. Query and source tile sizes bound each pairwise XYZ
difference tensor; Current and Varifold inner products accumulate tiles
without full face-by-face kernel/orientation matrices. This path is
non-approximate but changes floating reduction order. An explicit public
workflow setting now carries the plan through the complete optimizer,
reconstructions, PCA endpoints, nested bundle, outer run provenance, and
verifier cross-checks. Workload v0.2 accounts for exact logical pairs and the
configured execution tile, and benchmark v0.3 measures that same plan; a
v0.4 benchmark can measure one separately recorded effective blockwise tile
shape. A prospective multi-size scaling study remains open. The tile shape
bounds a single pairwise allocation; standard autograd may still retain
multiple tile graphs, so reduced peak RAM remains a measurement gate.

The low-level primitives and direct `GaussianTilePlan` expose a `recompute`
strategy that places deterministic tile calculations behind non-reentrant
activation checkpointing. The plan now reaches complete Subject/Atlas
objectives and the block optimizer, trading additional backward computation
for a smaller tested saved-tensor graph. Public `PairwiseEvaluationPlan`,
workflow configuration, and provenance intentionally remain standard-only. The
benchmark protocol can measure either strategy in separately declared fresh
processes, but a prospective representative study still has to establish the
tradeoff;
saved-tensor counts are not peak-RAM claims.

This vertical path is not yet the common production backend shown above. Its
child-process transport and source GUI supervision now exist, but it does not
implement the reference lifecycle's checkpoint/resume operations, parent-death
crash recovery, or reference-engine supervision.
An optimized kernel or GPU path must reproduce the dense baseline before it can
replace this correctness implementation.

## Security and privacy boundary

The application is local-first. A run does not upload meshes, metadata, logs,
or telemetry unless a future feature obtains explicit user consent. Paths and
specimen identifiers must be reviewed before public diagnostic bundles are
created.

## Open questions

- exact mesh library for robust VTK/PLY/STL/OBJ inspection;
- container strategy for Windows, Linux, and HPC;
- validation of checkpoint compatibility beyond the identical frozen backend;
- portable path representation and privacy-preserving diagnostic exports;
- quantitative comparison formats and tolerance governance.
