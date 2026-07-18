# Desktop executable and installer architecture

Status: **project setup, parameter/workload review, verified Modern
start/live-event/cancel/result review, and a developer-only Windows one-directory
evidence build exist; no distributable binary or installer yet**

Tracked by [engineering issue #22](https://github.com/heinjenny95/DiffeoForge/issues/22)
and [ADR 0003](decisions/0003-windows-desktop-distribution.md). The
machine-readable boundary is
`distribution/desktop-contract-v0.1.json`.

## User-facing target

The first installable application will be Windows x86-64, CPU-first, and usable
without a pre-existing Python installation. The planned user path is:

1. install a signed DiffeoForge setup executable;
2. select a mesh/project directory;
3. optionally import and review homologous landmarks and aligned mesh copies;
4. review preflight, parameters, resource estimate, and selected engine;
5. start/cancel/resume compute in a worker process;
6. inspect the atlas, convergence evidence, PCA tables/plots, and provenance;
7. export a reproduction bundle that does not contain unpublished data unless
   the user explicitly includes them.

PySide6 is the current GUI direction because it is the official Qt for Python
binding and supports Windows, Linux, and macOS. The first source-only GUI slice
is available through the optional `desktop` dependency and is documented in
[Desktop project-setup preview](DESKTOP_PREVIEW.md). Only the official
`PySide6-Essentials` distribution is currently required; PySide6 remains absent
from the base CLI dependencies. Its preliminary LGPLv3/GPLv3/commercial boundary is
documented, but exact-module licensing, notices, corresponding-source and
relinking obligations still block redistribution of a frozen binary. Qt's
official documentation lists both PyInstaller and the Nuitka-based
`pyside6-deploy`; the first packaging spike will compare their frozen artifacts
before locking exact tool versions.

## Process and backend boundary

The GUI may call fast shared-core validation and report functions in process.
Numerical compute runs in a child worker process with an immutable run
directory. This isolates PyTorch memory, makes cancellation observable, and
keeps a GUI failure from silently corrupting accepted run state. The strict
source-level Modern CPU transport and its fail-closed parent controller are now
implemented and documented in
[Versioned desktop worker protocol](DESKTOP_WORKER.md). The controller binds
events to the reviewed request, enforces lifecycle/exit-code agreement, bounds
  stderr, and independently verifies successful output. Source GUI step 3 now
  binds the reviewed configuration hash, runs that controller outside the Qt
  event loop, displays exact events, and requests cooperative cancellation.
  Source GUI step 4 reruns the full shared-core Modern verifier outside the GUI
  thread, presents bounded Atlas/optimizer/PCA/QC evidence, and rechecks the two
  manifest hashes plus selected artifact size/SHA-256 immediately before OS
  handoff. It does not implement an internal VTK renderer. Parent-death recovery
  and abandoned-private-directory reconciliation remain separate unfinished
  slices. The Windows controller now contains each worker in a dedicated
  kill-on-close Job Object and treats command-pipe EOF as cross-platform
  cooperative parent disconnect. The first frozen-process engineering
  slice is documented in [Windows one-directory freeze evidence](WINDOWS_FREEZE_EVIDENCE.md):
  it creates separate windowed-parent and pipe-worker executables, exercises
  their production protocol on a public synthetic configuration, and binds an
  exact-file inventory to a clean source commit. It is not release evidence.
  A separate manually triggered GitHub-hosted Windows workflow can repeat that
  complete freeze and smoke contract on a fresh runner. It uploads only the
  exact manifest and hash sidecar, never the unsigned executable directory;
  each run remains engineering evidence and must be independently inspected.
  The first such clean-runner observation completed successfully on 18 July
  2026 and its downloaded two-file evidence artifact was independently checked;
  its exact source, inventory, hashes, observations, and remaining release gates
  are recorded in the linked evidence document.
  Current manual runs additionally create an exact, externally freeze-hash-bound
  [installed-distribution metadata inventory](DESKTOP_DEPENDENCY_METADATA_EVIDENCE.md)
  with hashed license-related files. Every package remains explicitly
  unreviewed; this is an input to, not a substitute for, license review and an
  SBOM. A separate [deterministic SBOM tool](DESKTOP_SBOM.md) can now create and
  independently verify CycloneDX 1.7 from the exact freeze and dependency
  evidence. The manual clean-runner workflow is now configured to create and
  verify all three exact pairs, while the latest independently inspected
  observation remains the earlier four-file artifact until a new dispatch is
  completed and downloaded.

The CPU modern engine is the first bundled numerical variant. A future NVIDIA
build is a separate artifact with separate numerical evidence; the application
must not download or swap compute runtimes behind the user's back. PyTorch's
official installer already distinguishes Windows CPU and CUDA selections, so a
single ambiguous "works everywhere" bundle would hide a material dependency
and validation difference.

The desktop preview renders the shared-core `modern-plan` workload contract in
its second step and publishes the strict JSON/HTML report beside the generated
configuration. It retains the distinction between exact logical all-pairs
counts, the largest configured dense or blockwise execution tile, known payload
subtotals, host observations, and unknown measured peak RAM/runtime. The
Deformetrica route instead renders its existing preflight parameter ratios and
labels resource use as unmodelled because computation remains external.

The reviewed template can now be displayed without adding a visualization
runtime: an immutable Qt-independent model supplies bounded XY/XZ/YZ wireframe
projections to QtGui's QPainter. Large meshes use a deterministic, explicitly
reported display-edge budget. The widget never edits or decimates the source
mesh and is not an interactive 3D or landmark-placement dependency.

The shared-core `modern-run` callback supplies the worker-to-UI progress
payload. The v0.1 worker serializes the same strict dictionaries across the
process boundary inside its own versioned event envelope. It also accepts one
versioned cooperative cancellation command and guarantees that cancellation at
a safe point removes private temporary work without publishing a destination.
The Modern path remains explicitly nonresumable because it has no checkpoints.
Neither worker nor GUI may turn stage/decision counts into an unmeasured
runtime percentage or ETA.

The Qt bridge queues a cancel request even if it arrives before its thread-pool
task starts. A normal window close during compute is deferred while the same
cooperative cancellation completes. This is not operating-system crash
recovery; forced termination and power loss still require a future startup-time
reconciliation contract.

`modern-benchmark` provides measured objective/gradient observations for a
user-selected subject count and the explicitly configured dense or blockwise
plan. A blockwise benchmark can additionally declare standard or recompute
autograd without changing the atlas workflow. A GUI must display that choice,
render its strict JSON and raw repeats, retain the 5 ms sampled-RSS limitation,
and not extrapolate a microbenchmark into a full-run ETA or a 300-subject
feasibility verdict.

Deformetrica 4.3 remains an external reference backend. Its Python 3.8 stack is
not copied into the desktop executable. Desktop step 2 can now bind the exact
reviewed container engine/image to the existing read-only `doctor` checks and
show their raw status, summary, and guidance outside the GUI thread. It neither
installs nor starts that environment, and the reference compute button remains
disabled until a separately tested process supervisor exists.

The read-only prelaunch layer can now serialize the exact reviewed hash,
container settings, normalized run ID, and resolved destination through a
versioned JSON Schema. It rechecks those inputs without creating the destination
or starting a process. The eventual supervisor must consume and reverify this
request inside its contained child; this contract alone does not unlock the
reference button.

The reference route also has a separate schema-valid worker event vocabulary
and parent-side lifecycle ledger. Unlike Modern cancellation, it explicitly
distinguishes stopping before preparation, retaining an immutable prepared run,
and interrupting active execution with a terminal result hash.

A source-level nonnumerical harness consumes it over real stdin/stdout, rechecks
the prelaunch request in the child process, and guarantees a terminal stop
before preparation. A Qt-independent parent controller now attaches that child
to the Windows kill-on-close Job, bounds output, enforces a timeout, reconciles
the exact harness lifecycle, and independently reverifies the request. The
evidence build now freezes this harness as the sibling
`DiffeoForgeReferenceWorker.exe` and makes its exact three-event
`stopped_before_prepare` smoke mandatory before bundle evidence can be
written. A second mandatory audit starts that frozen worker suspended, assigns
it through the real controller to the Windows kill-on-close Job, hard-exits the
controller, and verifies bounded worker termination. No run is prepared and no
reference compute control is enabled.

A separate child can consume an independently hash-bound
preparation-only approval and atomically publish a verified immutable run with
terminal outcome `prepared_not_executed`. It has its own narrow request/event
schemas and does not alter the frozen nonnumerical worker. The evidence build
now freezes it as `DiffeoForgeReferencePreparationWorker.exe` and requires a
real five-event controller smoke using an externally created, independently
hash-bound approval before v0.3 evidence can be written. It is not exposed by
the GUI; that remains a separate product and safety gate.

The child has a Qt-independent parent controller that performs that
Job assignment before request delivery, bounds transport and runtime, and
independently verifies the published prepared run. A source parent resolves the
Python module; a frozen parent resolves only the dedicated sibling beside its
own executable. Source and frozen siblings now each have a dedicated
suspended-worker hard-parent-death
audit at the real Job-assignment boundary. These pre-request gates do not prove
recovery or containment after preparation begins; installer integration and
GUI enablement remain open. See
[frozen preparation-worker parent-death evidence](FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md).

## Bundle and installer decisions

The first evidence build now uses pinned PyInstaller 6.21.0 in one-directory
mode, not a single-file executable. PyInstaller documents that one-file applications
extract bundled content into a temporary directory at launch. A large,
long-running scientific application containing Qt and PyTorch benefits from an
inspectable installed directory, no repeated temporary extraction, simpler DLL
inventory, and clearer antivirus/signing diagnostics.

Inno Setup is the proposed Windows installer wrapper. Its official toolchain can
compile scripts noninteractively, install per-user or administratively, create
signed installers/uninstallers, log setup, support Unicode paths, and perform
silent installs for clean-VM CI. The installer contains the already frozen
one-directory application; it does not resolve Python packages on the user's
computer.

The evidence pin is not the future release lock. Exact Qt, PyTorch, transitive
dependencies, and Inno Setup versions still belong in a reviewed release lock
and SBOM. No unpinned `latest` downloads may occur during a release build.
The first SBOM design is now fixed by
[ADR 0005](decisions/0005-cyclonedx-post-build-sbom.md) as deterministic
CycloneDX 1.7 JSON generated only from externally hash-bound freeze and
dependency evidence. The machine contract is
`distribution/windows/sbom-contract-v0.1.json`. The implemented generator
requires exact external hashes for both source-evidence documents, refuses
overwrite and output inside the bundle, and reconstructs the mapping during
verification. This does not satisfy license or redistribution review.

Primary packaging references:

- [PyInstaller usage and one-directory/one-file modes](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller spec files and one-file extraction](https://pyinstaller.org/en/stable/spec-files.html)
- [Qt for Python deployment options](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Qt for Python `pyside6-deploy`](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
- [PyTorch local CPU/CUDA selection](https://pytorch.org/get-started/locally/)
- [Inno Setup capabilities](https://jrsoftware.org/isinfo.php)
- [Inno Setup command-line compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)

## Files and privacy

Installed application files and user projects never share a directory. Meshes,
landmarks, runs, and results stay under a user-selected project root. Per-user
application settings contain preferences only. Uninstall preserves project
data. The default application performs no telemetry, update check, model
download, or mesh upload; any future network feature requires a separate
consent and threat-model decision.

## Installer release gates

Before an installer may be called usable, CI and a named human reviewer must
demonstrate on a clean Windows VM with no Python/developer tools:

- offline install, launch, `doctor`, public CC0 smoke, exit, and uninstall;
- current-user and administrator installation behavior;
- spaces, long paths, and non-ASCII project/specimen names;
- Authenticode signature, SHA-256 checksums, SBOM, and license inventory;
- Windows Defender scan and DLL inventory;
- interruption/crash recovery without a surviving worker or mutable partial
  result presented as complete (Windows parent-death termination evidence now
  exists for both the Modern and frozen-reference worker boundaries;
  power-loss and abandoned-state reconciliation remain open);
- installer/uninstaller logs and preservation of user projects;
- no network requests by default;
- CPU numerical validation on the exact bundled artifact.

GPU, Linux, macOS, and HPC distributions receive separate gates. A developer
machine smoke test is not clean-machine evidence.
