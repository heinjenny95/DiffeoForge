# Windows one-directory freeze evidence

Status: **developer-machine engineering evidence, not a release, installer, or
redistributable binary**

## Manual clean-runner workflow

`.github/workflows/windows-freeze-evidence.yml` provides a deliberately manual
`workflow_dispatch` path for repeating this engineering build on a fresh
GitHub-hosted `windows-latest` runner. It has read-only repository permission,
uses pinned checkout/setup/upload action commits, selects Python 3.12, checks
the pinned PyInstaller and CPU-only Torch boundary, and stages all public
synthetic configs, meshes, approval, and destinations under `RUNNER_TEMP` so
the checkout remains clean.

The workflow invokes the same `build-evidence.ps1` contract. Therefore a
successful run must pass the frozen GUI smoke, full public Modern
worker/controller smoke, nonnumerical reference harness, reference
hard-parent-death audit, preparation-worker hard-parent-death audit, real
approval-bound prepared-not-executed worker/controller smoke, exact bundle
inventory creation, and an independent final verification.

The unsigned one-directory bundle is intentionally not uploaded. The workflow
copies `freeze-evidence.json` and its sidecar, creates a separately hash-bound,
explicitly unreviewed installed-distribution metadata inventory and sidecar,
then creates the deterministic CycloneDX 1.7 document and sidecar from both
source-evidence hashes. The configured boundary is exactly those six regular,
non-reparse files retained for 14 days. All three pairs are independently
verified immediately before upload. See
[Frozen dependency metadata evidence](DESKTOP_DEPENDENCY_METADATA_EVIDENCE.md)
and [Deterministic Windows post-build SBOM](DESKTOP_SBOM.md).
The workflow does not run on pushes or pull requests and therefore cannot
silently consume a large Windows runner for ordinary changes.

The workflow's existence is not a successful clean-runner observation. Each
manual run must be linked and its downloaded exact artifact independently
inspected before it is cited as engineering evidence.

### First clean-runner observation

[Workflow run 29634117568](https://github.com/heinjenny95/DiffeoForge/actions/runs/29634117568)
successfully repeated the complete contract on a fresh GitHub-hosted
`windows-latest` runner on 18 July 2026. The run was manually dispatched from
clean source commit `a690473eb7527c9fc9b7a75068d7a9e6b730aeb3`, used Python
3.12.10 and PyInstaller 6.21.0, and completed in 10 minutes 18 seconds. Its
build-and-verify step took 8 minutes 34 seconds.

The run observed all of the following through the frozen executables:

- the GUI smoke exited successfully;
- the public synthetic Modern worker completed with 21 accepted events and
  published to a destination containing spaces and `Käfer`;
- the nonnumerical reference harness emitted the exact three-event
  `stopped_before_prepare` outcome and created no destination;
- hard controller death stopped the suspended reference worker within the
  audit deadline and created no destination;
- hard controller death stopped the suspended preparation worker before
  request delivery, with no destination, private stage, or engine start; and
- the externally approved preparation request emitted the exact five-event
  `prepared_not_executed` outcome, published an independently verified
  destination, and did not start engine execution.

This first observation predates the dependency-metadata extension. Its
independently downloaded artifact contained exactly
`freeze-evidence.json` and `freeze-evidence.sha256`. The manifest is schema
`desktop-freeze-evidence-v0.3`, has SHA-256
`69b208e178bb6181ec7c73bd7abd8f9c409fc4a4deeeb246bb374ee033c6c4b6`,
and its sidecar matched exactly. It records four expected entry points, 2,656
files, 671,170,553 bytes, and inventory SHA-256
`b18be2d86ad9ae6fc2b301471abea0735f0f7c1980fcf2a14a0f42b9eae95c46`.
The GitHub artifact was ID `8426575477`; its uploaded archive digest was
`sha256:9e4b808af5930a5a4d08c3f2e14f05f0e7cf694a15abde7eeb6197f5b806fef3`.

This observation remains `engineering_evidence_not_a_release`. In particular,
the unsigned 671 MB executable directory was deliberately not uploaded, and
the run did not satisfy Authenticode, SBOM, dependency-license, Windows
Defender, no-network, installer/uninstaller, clean installed VM, crash
reconciliation, CPU numerical release-validation, or scientific-validation
gates.

### First four-file dependency-metadata observation

[Workflow run 29635525566](https://github.com/heinjenny95/DiffeoForge/actions/runs/29635525566)
repeated the complete frozen-process contract from clean commit
`ac10b0953f6c4ad11bd98001694726d6ed870d2d` and successfully added the
freeze-hash-bound dependency-metadata pair. The independently downloaded
artifact contained exactly four files; both exact sidecars and both schemas
verified. The bundle recorded 2,657 files and 671,225,043 bytes. The metadata
pair recorded 27 packages and 152 hashed installed license-related files with
no unresolved `License-File` declaration. Exact artifact hashes, package-field
counts, timings, and the unchanged license/SBOM non-claims are documented in
[Frozen dependency metadata evidence](DESKTOP_DEPENDENCY_METADATA_EVIDENCE.md).

### Pending six-file SBOM observation

The workflow source now requires the pinned builder-only SBOM dependency,
creates the deterministic CycloneDX pair only after both source-evidence pairs
verify, reconstructs the SBOM through the independent download verifier, and
fails unless the upload directory contains exactly the six approved regular,
non-reparse files. This integration is not itself an observation. A new manual
run, independent artifact download, exact hash audit, and documentation update
are still required before a clean-runner SBOM is cited.

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
