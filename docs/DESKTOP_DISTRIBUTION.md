# Desktop executable and installer architecture

Status: **architecture and release gates only; no installer exists yet**

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
binding and supports Windows, Linux, and macOS. It is not added as a runtime
dependency until the first GUI slice exists and its LGPLv3/GPLv3/commercial
licensing obligations have been reviewed. Qt's official documentation lists
both PyInstaller and the Nuitka-based `pyside6-deploy`; the first packaging
spike will compare their frozen artifacts before locking exact tool versions.

## Process and backend boundary

The GUI may call fast shared-core validation and report functions in process.
Numerical compute runs in a child worker process with an immutable run
directory. This isolates PyTorch memory, makes cancellation observable, and
keeps a GUI failure from silently corrupting accepted run state.

The CPU modern engine is the first bundled numerical variant. A future NVIDIA
build is a separate artifact with separate numerical evidence; the application
must not download or swap compute runtimes behind the user's back. PyTorch's
official installer already distinguishes Windows CPU and CUDA selections, so a
single ambiguous "works everywhere" bundle would hide a material dependency
and validation difference.

The shared-core `modern-plan` workload report is the first implementation of
the resource-review step. A future GUI may render its strict JSON, but must
retain the report's distinction between exact dense operation counts, known
payload subtotals, and unknown measured peak RAM/runtime.

The shared-core `modern-run` callback is the first implementation of the
worker-to-UI progress payload. Its strict v0.1 JSON shape reports seven
completed workflow stages and committed optimizer decisions. The desktop
worker may serialize those events across a process boundary, but must not turn
stage/decision counts into an unmeasured runtime percentage or ETA.

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
