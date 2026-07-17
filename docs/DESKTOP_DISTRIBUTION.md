# Desktop executable and installer architecture

Status: **project setup, parameter/workload review, and a source-level Modern
worker protocol exist; no frozen executable or installer exists yet**

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
stderr, and independently verifies successful output; GUI execution controls
and frozen-process packaging remain separate unfinished slices.

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

The shared-core `modern-run` callback supplies the worker-to-UI progress
payload. The v0.1 worker serializes the same strict dictionaries across the
process boundary inside its own versioned event envelope. It also accepts one
versioned cooperative cancellation command and guarantees that cancellation at
a safe point removes private temporary work without publishing a destination.
The Modern path remains explicitly nonresumable because it has no checkpoints.
Neither worker nor GUI may turn stage/decision counts into an unmeasured
runtime percentage or ETA.

`modern-benchmark` provides measured objective/gradient observations for a
user-selected subject count and the explicitly configured dense or blockwise
plan. A blockwise benchmark can additionally declare standard or recompute
autograd without changing the atlas workflow. A GUI must display that choice,
render its strict JSON and raw repeats, retain the 5 ms sampled-RSS limitation,
and not extrapolate a microbenchmark into a full-run ETA or a 300-subject
feasibility verdict.

Deformetrica 4.3 remains an external reference backend. Its Python 3.8 stack is
not copied into the desktop executable. `doctor` will detect a separately
installed version-checked native/container route and explain how it differs
from the bundled modern CPU engine.

## Bundle and installer decisions

The first evidence build uses PyInstaller's default one-directory mode, not a
single-file executable. PyInstaller documents that one-file applications
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

Exact PyInstaller, Qt, PyTorch, and Inno Setup versions belong in a release lock
and SBOM, not this architectural contract. No unpinned `latest` downloads may
occur during a release build.

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
  result presented as complete;
- installer/uninstaller logs and preservation of user projects;
- no network requests by default;
- CPU numerical validation on the exact bundled artifact.

GPU, Linux, macOS, and HPC distributions receive separate gates. A developer
machine smoke test is not clean-machine evidence.
