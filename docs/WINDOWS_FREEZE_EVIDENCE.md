# Windows one-directory freeze evidence

Status: **developer-machine engineering evidence, not a release, installer, or
redistributable binary**

DiffeoForge can be frozen on a 64-bit Windows development machine into one
directory containing four entry points:

- `DiffeoForge.exe` is the windowed Qt application and does not allocate a
  console;
- `DiffeoForgeWorker.exe` is the pipe-only numerical worker launched by the
  desktop parent;
- `DiffeoForgeReferenceWorker.exe` is the pipe-only, deliberately
  nonnumerical reference harness supervised by its dedicated parent controller.
- `DiffeoForgeReferencePreparationWorker.exe` is the separate approval-bound,
  preparation-only worker; it cannot authorize or start engine execution.

The workers remain separate so their parents can enforce the corresponding
versioned request/event protocols, containment, immutable destinations, and
independent verification. A frozen parent resolves its worker beside its own
executable. A source checkout continues to use Python module entry points.

This slice uses PyInstaller 6.21.0 in its documented one-directory mode. The
builder-only pin is in `distribution/windows/freeze-requirements.txt`; it is
not a complete release lock or SBOM. The build spec collects the DiffeoForge
schemas and creates the four executables in one shared bundle. It does not
include the external Deformetrica 4.3 environment.

## Reproduce the evidence build

Start from a clean Git checkout on 64-bit Windows with Python 3.12. The build
script deliberately refuses a dirty worktree and refuses to overwrite either
its bundle or work directory.

```powershell
py -3.12 -m venv .freeze-venv
.freeze-venv\Scripts\python.exe -m pip install -e ".[desktop,modern-engine]"
.freeze-venv\Scripts\python.exe -m pip install -r distribution\windows\freeze-requirements.txt
```

For the stronger smoke, create a public synthetic Modern configuration outside
tracked source files. A path with spaces and non-ASCII characters is useful
because both the JSON-lines transport and Windows process boundary must retain
it exactly.

The preparation smoke additionally requires a previously reviewed, externally
created preparation-only approval, its current exact config, and the
independently recorded SHA-256 of the complete approval file. The build never
manufactures approval. The approved destination must still be absent.

```powershell
.freeze-venv\Scripts\diffeoforge.exe modern-init `
  examples\synthetic\meshes `
  --units millimeter `
  --config "dist\Frozen Smoke Käfer\modern.yaml" `
  --output-directory "dist\Frozen Smoke Käfer\configured output" `
  --max-cycles 1

powershell -File distribution\windows\build-evidence.ps1 `
  -Python .freeze-venv\Scripts\python.exe `
  -DistPath "dist\Frozen Evidence Käfer" `
  -WorkPath "dist\Frozen Evidence Work Käfer" `
  -SmokeConfig "dist\Frozen Smoke Käfer\modern.yaml" `
  -SmokeDestination "dist\Frozen Smoke Käfer\atlas result" `
  -PreparationApproval "C:\evidence-input\preparation-approval.json" `
  -PreparationConfig "C:\evidence-input\reference.yaml" `
  -PreparationApprovalSha256 $approvalSha256
```

The script checks the Python, PyInstaller, CPU-only PyTorch, Windows, x86-64,
and clean-source boundaries. It then:

1. builds the one-directory bundle;
2. launches the frozen GUI's noninteractive `--smoke` path;
3. optionally runs the supplied public configuration through the frozen worker
   using the production parent controller;
4. always runs the frozen nonnumerical reference harness through its contained
   parent controller, requires the exact three-event `stopped_before_prepare`
   lifecycle, and verifies that it created no destination;
5. hard-exits a real controller immediately after it assigns a suspended frozen
   reference worker to the Windows kill-on-close Job, then requires that worker
   to terminate within the bounded audit deadline;
6. hard-exits the real preparation controller immediately after assigning the
   suspended frozen preparation sibling to the Job, then requires bounded
   worker termination, zero request delivery, zero destination/private-stage
   mutation, and unchanged authorization inputs;
7. runs the frozen approval-bound preparation worker through its real parent
   controller, requires the exact five-event `prepared_not_executed` lifecycle,
   independently reverifies the published run, and confirms no engine started;
8. records the exact source commit, builder/runtime package versions, every
   bundled relative path, byte count, file SHA-256, aggregate byte count, and
   inventory SHA-256;
9. writes `freeze-evidence.json` and its `freeze-evidence.sha256` sidecar;
10. immediately re-verifies the sidecar and exact file inventory.

`tools/desktop_bundle_evidence.py verify <bundle>` can repeat the final
verification. It fails closed on a changed manifest, unsafe path, missing,
extra, reordered, resized, or rehashed file, unexpected entry point, or a
status outside the versioned engineering-evidence schema. Evidence creation is
non-overwriting. New evidence uses schema v0.3 and requires all four entry
points. The verifier retains explicit read-only support for genuine v0.1
two-entry-point and v0.2 three-entry-point manifests; it never silently
reinterprets either as v0.3.

## First developer-host observation

A pre-commit packaging diagnostic on 17 July 2026 produced 2,600 inventoried
files totalling 604,863,934 bytes (576.84 MiB). The environment used Python
3.12.13, PyInstaller 6.21.0, PySide6-Essentials/Shiboken6 6.11.1, CPU-only
PyTorch 2.13.0, and NumPy 2.5.1. The GUI smoke passed, and a five-subject public
synthetic Modern workflow completed through the frozen worker/controller with
15 accepted protocol events in a destination path containing spaces and
`Käfer`. This diagnostic found and then confirmed the repair of a Windows
console-code-page corruption at the worker boundary.

These numbers describe that one diagnostic, not a size promise or final
artifact. Every clean-commit build records its own complete resolved package
map, byte total, file count, and hashes in `freeze-evidence.json`; that manifest
is authoritative for its directory.

## What this proves

One successful evidence build proves only that the recorded clean source commit
was frozen on the recorded Windows developer host, its four entry points were
present, the GUI smoke exited successfully, the nonnumerical reference harness
stopped before preparation through its real frozen worker/controller boundary,
the suspended reference worker terminated after hard controller death through
the real Windows Job boundary,
the suspended frozen preparation worker terminated after hard controller death
before request delivery without creating a destination or private stage,
one externally approved reference run reached the independently verified
`prepared_not_executed` state through the real frozen preparation
worker/controller boundary without starting an engine,
the optional recorded synthetic Modern workflow completed through its real
frozen worker/controller boundary, and the resulting directory matched its
exact-file inventory at verification time.

The manifest intentionally labels itself
`engineering_evidence_not_a_release`. It is not evidence of:

- an installer or uninstaller;
- Authenticode signing or Windows Defender acceptance;
- a complete dependency lock, SBOM, third-party license inventory, or
  redistribution approval;
- installation and execution on a clean Windows VM without Python;
- absence of network access;
- crash reconciliation or recovery after parent death, power loss, or forced
  termination;
- numerical release equivalence, biological validity, GPU behavior, or
  feasibility for 300-specimen cohorts.

Those remain explicit release gates in
[Desktop executable and installer architecture](DESKTOP_DISTRIBUTION.md) and
must not be inferred from a developer-machine smoke.

The exact hard-exit method and why a suspended child rules out pipe-EOF or
normal-exit false positives are documented in
[Frozen reference-worker parent-death evidence](FROZEN_REFERENCE_PARENT_DEATH.md).
The external-approval requirement and exact five-event frozen preparation gate
are documented in
[Frozen approval-bound reference preparation worker](FROZEN_REFERENCE_PREPARATION_WORKER.md).
The frozen preparation pre-request crash gate is documented in
[Frozen preparation-worker parent-death evidence](FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md).

## Primary packaging references

- [PyInstaller usage and one-directory mode](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller spec files](https://pyinstaller.org/en/stable/spec-files.html)
- [Qt for Python deployment options](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Qt for Python deployment with PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
