# DiffeoForge

> [!WARNING]
> **Pre-alpha research software.** DiffeoForge is not yet validated for
> scientific production use. Its experimental reference backend can invoke a
> hash-locked Deformetrica 4.3.0 CPU container, but scientific equivalence,
> cross-platform distribution, and production-scale use are not yet validated.

DiffeoForge is the working title for an open-source, reproducible workflow for
diffeomorphic atlas construction from 3D surface meshes. The project aims to
make landmark-free atlas estimation usable by researchers without requiring
Python, notebook, XML, or CUDA expertise while preserving full access to every
scientific parameter and generated file.

The project is being developed in public from its first engineering decisions.
The name may change before the first release.

## Intended user experience

The eventual application should support both a graphical interface and the
same operations from a command line:

```text
Select mesh directory
  -> validate meshes and configuration
  -> review warnings and estimated resource use
  -> generate explicit engine configuration
  -> estimate atlas
  -> inspect convergence and quality report
  -> export a reproducible run bundle
```

The current command-line workflow is:

```bash
diffeoforge validate atlas.yaml
diffeoforge reference-plan atlas.yaml --run-id experiment-001
# Review exact paths, staged inputs, effective YAML, XML bytes/hashes, and command.
# Optionally create an offline browser review while retaining JSON on stdout:
diffeoforge reference-plan atlas.yaml --run-id experiment-001 --report experiment-001-preparation.html > experiment-001-preparation.json
diffeoforge reference-plan-verify experiment-001-preparation.json --report experiment-001-preparation.html
# After human review, record preparation-only approval for that exact fingerprint:
diffeoforge reference-plan-approve atlas.yaml --run-id experiment-001 --approve-fingerprint REVIEWED_SHA256 --output experiment-001-approval.json
diffeoforge reference-plan-approval-verify experiment-001-approval.json --current-config atlas.yaml
diffeoforge reference-prepare-approved experiment-001-approval.json --current-config atlas.yaml --expect-request-sha256 REVIEWED_REQUEST_SHA256
# Inspect manifest.json and engine/*.xml before committing compute time.
diffeoforge execute runs/experiment-001
diffeoforge status runs/experiment-001
diffeoforge report runs/experiment-001

# Or prepare and execute a new run in one command:
diffeoforge run atlas.yaml --run-id experiment-002

# If a terminal failed/interrupted run has an inventoried checkpoint:
diffeoforge resume runs/experiment-001 --run-id experiment-001-resume-01
```

If the Python Scripts directory is not available on `PATH`, the packaged
fallback `python -m diffeoforge` invokes this exact same parser and commands;
it is not a separate workflow implementation.

The generic `prepare` command does not consume an approval. The stricter
`reference-prepare-approved` path requires an externally recorded request hash,
exact-matches private staging to the approved plan, publishes atomically, and
stops before execution. Approval never authorizes engine execution.

Prepared run directories are write-once. DiffeoForge refuses to overwrite or
execute one a second time. Resume creates a new immutable successor and preserves
the source run.

## Design principles

- **No hidden defaults:** effective values are written to every run manifest.
- **Engine independence:** workflow logic is separated from numerical engines.
- **Reference before replacement:** a frozen Deformetrica backend will establish
  reference behavior before a modern engine is accepted.
- **Fail before compute:** invalid paths, meshes, units, and parameter ranges
  should be detected before an expensive run starts.
- **Immutable runs:** inputs, configuration, software versions, hashes, logs,
  and outputs are stored together and never silently overwritten.
- **Scientific validation:** numerical plausibility is not treated as evidence
  of equivalence or correctness.
- **No AI dependency:** AI tools may assist development, but users will never
  need an AI service to run the software.

## Current milestone

This repository currently provides:

- versioned, machine-readable atlas-configuration and run-manifest schemas;
- geometry-aware preflight for classic and VTK 5.1 triangular PolyData;
- deterministic input discovery, staging, SHA-256 inventories, and immutable
  run directories;
- a versioned read-only reference preparation plan with exact future staged
  paths, effective YAML, Deformetrica XML contents/hashes, and command preview;
- a deterministic preparation-only approval request bound to a freshly
  recomputed exact plan, plus strict internal and optional current-state
  verification without preparation or engine authorization;
- an approval-aware atomic reference preparation path that externally binds the
  request bytes, exact-matches private staging, never replaces an appearing
  destination, and verifies pristine `prepared` state without engine launch;
- explicit Deformetrica XML generation and native or Windows-to-WSL launchers;
- exact command, environment, lifecycle, convergence, result, and output
  inventories;
- an engine-independent architecture decision;
- an explicit scientific validation strategy;
- automated linting, tests, and package-build checks;
- a deterministic CC0 synthetic mesh cohort for public integration tests;
- versioned Deformetrica outputs and a tolerance-based reference comparator;
- a read-only environment doctor and transparent mesh-directory initializer;
- an optional PySide6 desktop preview for non-overwriting mesh-folder
  validation, modern/reference project creation, effective-parameter review,
  hash-bound reference-environment and future-prelaunch inspection,
  shared-core workload/preflight evidence, and a verified Modern-only
  start/live-event/cancel screen followed by a fully reverified Atlas/PCA/QC
  summary with inventory-bound artifact handoff;
- a self-contained HTML input-validation and parameter-scale report;
- a self-contained HTML convergence, lifecycle, and result report;
- terminal interruption capture, explicit unclean-stop recovery, and
  provenance-bound checkpoint successors;
- contribution and AI-usage policies suitable for public research software;
- an experimental dense-PyTorch numerical baseline with full per-subject
  Current/Varifold objective and gradient comparisons against Deformetrica 4.3,
  plus deterministic momenta-only and full-parameter block-optimization
  prototypes with versioned CC0 evidence and cross-platform CI.
- an immutable experimental modern-atlas result bundle containing estimated
  template/reconstruction meshes, parameters, optimizer history, artifact
  hashes, a complete open CSV/JSON momenta-PCA handoff, static SVG plots, and
  reproducible mean/±PC deformation meshes;
- an experimental end-to-end modern workflow that inventories a mesh folder,
  optionally applies labelled-landmark Procrustes transforms, initializes and
  runs the CPU/float64 engine, and publishes a doubly verified immutable run;
- deterministic raw/effective-input and generated-output mesh-quality evidence
  with explicit topology/triangle gates, JSON/CSV reports, local face-area
  ratios, atomic rejection, and verifier-side recomputation;
- a pre-compute configured-engine workload plan with instrumented all-pairs
  operation-count formulas, exact dense/blockwise execution-tile payloads,
  host observations, and explicit refusal to invent peak-RAM or runtime
  predictions;
- versioned live workflow and committed optimizer-decision events used by the
  CLI and transported unchanged by a strict child-process desktop worker,
  including reviewed-configuration hash binding and nonpublishing cooperative
  cancellation; a Qt-independent parent controller validates event identity,
  sequence, lifecycle, exit status, bounded diagnostics, and completed results
  without invented percent-complete or ETA claims;
- an opt-in fresh-process objective/gradient benchmark with explicit subject
  selection, raw repeats, sampled process RSS, exact provenance, explicit
  standard/recompute blockwise measurement, separately recorded benchmark-only
  effective rectangular tile plans, and no extrapolation to full-cohort runtime;
- an immutable prospective paired-benchmark design that freezes config/input
  hashes, subject-prefix sizes, repeats, and deterministic condition order
  before standard/recompute observations exist;
- explicit non-approximate blockwise Gaussian convolution, x-gradient,
  Current, and Varifold primitives with bounded tile tensors and dense
  forward/autograd parity, plus an explicit opt-in plan through the complete
  objective, optimizer, reconstructions, PCA meshes, and immutable public-run
  provenance; and an explicit direct-engine tile-recompute plan with complete
  objective/optimizer parity and saved-tensor evidence, not yet a public
  workflow setting or peak-RAM claim.

The experimental modern path is a public CLI/application-service workflow and
can now create and review a starter project through the GUI preview, bind the
launch to the reviewed configuration hash, show exact workflow/optimizer
events, request cooperative cancellation, and expose a detailed result view
only after the workflow, nested bundle, inventories, hashes, mesh QC, and SVG
safety checks pass again. Before worker launch, step 3 now shows the exact
destination, existing-result state, and any private candidate status/path/reason;
it checks again immediately before launch and never mutates recovery state.
Each selected result artifact is rechecked by size
and SHA-256 immediately before it is opened by a local application. The
external Deformetrica route can now run an explicit read-only, configuration-
hash-bound diagnostic of its exact container engine and image from review
step 2. A separate source-level child can also consume an independently
hash-bound preparation-only approval and atomically publish a verified
`prepared_not_executed` run through a strict pipe. It still cannot start or
supervise Deformetrica. A Qt-independent parent contains this child, bounds its
transport and independently verifies the prepared run. The same child is now a
fourth sibling in the evidence-only Windows freeze and has a mandatory real
frozen controller smoke based on an externally created, independently
hash-bound approval; it remains disabled in the GUI. The Modern path does not
provide checkpoint/resume. The real source preparation worker also has suspended-process Windows
hard-parent-death evidence before request delivery. For the Modern compute
worker, Windows parent death terminates the contained worker tree and
command-pipe EOF requests cooperative cancellation on every platform.
Versioned private markers and OS-released
leases now support exact-destination, read-only discovery after hard crashes;
automatic deletion, resume, and reconciliation remain deliberately open.
DiffeoForge can also load the selected template outside the GUI thread and
render deterministic native XY/XZ/YZ wireframe projections with an explicit
display-edge budget and exact source hash. This is an inspection preview, not
interactive 3D rendering, mesh QC, registration evidence, or landmark picking.
DiffeoForge also does **not** yet ship a desktop installer or redistributable
binary. A clean-commit, exact-inventory Windows one-directory
[engineering build](docs/WINDOWS_FREEZE_EVIDENCE.md) now exercises the GUI and
separate frozen workers, but it does not satisfy the installer/release gates.
DiffeoForge still does not provide interactive native 3D mesh rendering or
self-intersection detection, or promise
CPU/GPU equivalence or 300-specimen production performance. See the [modern-workflow
documentation](docs/MODERN_WORKFLOW.md) and [reference-backend
documentation](docs/REFERENCE_BACKEND.md) for the exact boundaries.
The desktop reference diagnostic has its own
[non-mutation contract](docs/REFERENCE_DESKTOP_READINESS.md).
The native projection preview is specified in
[Template projection preview](docs/TEMPLATE_PREVIEW.md).

## First run from a mesh directory

Check the computer, create a transparent starter configuration, and review its
automatically generated HTML preflight report:

```powershell
diffeoforge doctor
diffeoforge init "C:\path\to\meshes" --units millimeter
# Review atlas.yaml and atlas.preflight.html before computation.
diffeoforge run atlas.yaml --run-id pilot-001
diffeoforge report runs/pilot-001
```

`init` never guesses coordinate units or silently overwrites files. A file
named `template.vtk` can be detected automatically; otherwise pass
`--template`. Model parameters that were not explicitly supplied are labelled
as exploratory, geometry-scaled starting values in both the YAML and report.
See the [first-run workflow](docs/FIRST_RUN.md) for every check, parameter rule,
override, and scientific boundary.

For the experimental modern engine, no XML or historical Python environment is
needed. Generate and review its separate explicit configuration, then create
and verify one immutable Atlas/PCA run:

```powershell
python -m pip install -e ".[modern-engine]"
diffeoforge modern-init "C:\path\to\meshes" --units millimeter
# Review modern-atlas.yaml. Generated parameter values are exploratory.
diffeoforge modern-plan modern-atlas.yaml
# Review modern-atlas.workload/workload.html. It is not a runtime forecast.
# Optional measured microbenchmark; subject count is always explicit.
diffeoforge modern-benchmark modern-atlas.yaml --subjects 5
diffeoforge modern-run modern-atlas.yaml
diffeoforge modern-verify modern-atlas-run
# If a prior hard crash left private state, inspect it without changing files:
diffeoforge modern-private-status modern-atlas-run
```

The status command classifies a held lease as active and a released valid lease
as abandoned. Unattributed, invalid, indeterminate, and symbolic-link candidates
fail closed and require explicit review. It never deletes, renames, resumes, or
publishes. See the [private-run discovery contract](docs/PRIVATE_RUN_DISCOVERY.md).

For a configured blockwise plan, the microbenchmark can explicitly measure the
experimental recompute graph in separate fresh processes with
`--tile-autograd-strategy recompute`. This is a benchmark-only override, not a
`modern-run` setting, safe preset, peak-RAM claim, or automatic comparison.

It can also measure one effective rectangular tile plan without editing the
reviewed YAML. Both sizes are required together, and the resulting strict v0.4
report preserves source-declared and effective plans separately:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml --subjects 5 `
  --query-tile-size 128 --source-tile-size 256
```

Before collecting a paired study, freeze its pre-results design:

```powershell
diffeoforge modern-benchmark-design modern-atlas.yaml `
  --subjects 5 20 50 --repeats 7
```

The immutable JSON/sidecar/HTML artifact records the exact condition order but
does not execute, compare, or rank benchmarks. See the
[prospective benchmark-design protocol](docs/MODERN_BENCHMARK_STUDY.md).

Execute or resume that exact design with one command:

```powershell
diffeoforge modern-benchmark-study modern-atlas.benchmark-study `
  modern-atlas.yaml
```

Every condition remains a separate verified benchmark v0.3 report. The runner
publishes only integrity hashes and completion state, never a winner or
performance claim. While it runs, the CLI prints exact verified-condition
counts and identities, never elapsed-time percentages or ETA.

Inspection is read-only, and completed evidence has a dedicated verifier:

```powershell
diffeoforge modern-benchmark-study-status modern-atlas.benchmark-study.run
diffeoforge modern-benchmark-study-verify modern-atlas.benchmark-study.run
```

Freeze a prospective full-factorial multi-tile design from the same reviewed
base config, without running any condition:

```powershell
diffeoforge modern-benchmark-matrix-design modern-atlas.yaml `
  --subjects 5 20 50 `
  --tile-shape 64x64 --tile-shape 128x256 --repeats 7
```

The CLI reviews the exact cell and condition count before atomically publishing
strict `matrix-design.json`, SHA-256 sidecar, and escaped HTML. Ordered query ×
source shapes remain distinct, every cell contains adjacent `standard` and
`recompute` conditions, and a 1000-condition ceiling catches accidental
combinatorial explosions. This implements only the pre-results design gate in
[ADR 0004](docs/decisions/0004-prospective-multi-tile-matrix.md). The existing
v0.1 single-tile study remains unchanged.

```powershell
diffeoforge modern-benchmark-matrix-design-verify `
  modern-atlas.benchmark-matrix
```

Execute or resume the exact frozen matrix, then inspect or fully verify its
separate raw v0.4 reports:

```powershell
diffeoforge modern-benchmark-matrix-study `
  modern-atlas.benchmark-matrix modern-atlas.yaml
diffeoforge modern-benchmark-matrix-study-status `
  modern-atlas.benchmark-matrix.run
diffeoforge modern-benchmark-matrix-study-verify `
  modern-atlas.benchmark-matrix.run
```

The v0.2 matrix runner follows only a verified contiguous prefix, reconciles a
valid report found ahead of atomic state after interruption, and rejects the
unsafe inverse. Progress contains exact condition counts and tile identity, not
percentages or ETA. It never aggregates results, chooses a winner, or creates a
preset. See the
[matrix study protocol](docs/MODERN_BENCHMARK_MATRIX_STUDY.md).

Generated configurations declare dense evaluation explicitly. The exact
non-approximate blockwise path can instead be requested without code:

```powershell
diffeoforge modern-init "C:\path\to\meshes" --units millimeter `
  --pairwise-mode blockwise --query-tile-size 256 --source-tile-size 256
```

Those tile values are user choices, not validated presets. Both `modern-plan`
and `modern-benchmark` execute the reviewed dense or blockwise plan and record
logical all-pairs dimensions separately from the largest single execution
tile. They do not claim that the tile bound is total or peak RAM.

## Developer quick start

DiffeoForge currently requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

diffeoforge validate examples/minimal-atlas.yaml
diffeoforge prepare examples/minimal-atlas.yaml --run-id synthetic-smoke
# After executing a compatible reference run:
diffeoforge compare-reference examples/runs/synthetic-smoke reference/synthetic-v1
pytest
ruff check .
```

Modern-engine contributors install its optional dependency set and run the
machine-readable primitive comparison separately:

```bash
python -m pip install -e ".[dev,modern-engine]"
python -m diffeoforge.engine.reference \
  reference/modern-engine-v0.1/deformetrica-4.3.0-primitives.json
python -m diffeoforge.engine.reference \
  reference/modern-engine-v0.2/deformetrica-4.3.0-objective.json
diffeoforge modern-run examples/minimal-modern-atlas.yaml \
  --output modern-synthetic-smoke
diffeoforge modern-verify modern-synthetic-smoke
```

The primitive comparisons remain correctness probes. `modern-run` is an
experimental atlas command with a stricter artifact boundary, but it remains
subject to the validation and scaling gates in the modern-engine documentation.

The bundled example uses one template and five deterministic synthetic meshes.
It exercises geometry preflight and immutable run preparation without private
research data. Execution requires either a compatible external Deformetrica
installation or the frozen reference container below.

For an isolated, hash-locked Deformetrica 4.3.0 CPU environment, build the
reference container and use the container example:

```bash
docker build --platform linux/amd64 -f container/Dockerfile \
  -t diffeoforge-deformetrica:4.3.0-cpu .
diffeoforge run examples/minimal-atlas-container.yaml --run-id container-smoke
diffeoforge compare-reference \
  examples/runs/container-smoke reference/synthetic-v1
```

See the [container reference documentation](docs/CONTAINER_REFERENCE.md) for
the frozen dependency boundary, first-run compilation cost, security limits,
and workflow for another mesh directory.

## Documentation

- [Project specification](docs/PROJECT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Deformetrica reference backend](docs/REFERENCE_BACKEND.md)
- [Modern-engine feasibility baseline](docs/MODERN_ENGINE_FEASIBILITY.md)
- [Experimental momenta-only optimizer](docs/MOMENTA_OPTIMIZER.md)
- [Experimental full atlas optimizer](docs/FULL_ATLAS_OPTIMIZER.md)
- [Immutable modern atlas result bundle](docs/MODERN_ATLAS_BUNDLE.md)
- [Experimental modern mesh-folder workflow](docs/MODERN_WORKFLOW.md)
- [Deterministic mesh-quality evidence](docs/MESH_QUALITY.md)
- [Modern configured-engine workload planning](docs/MODERN_WORKLOAD.md)
- [Versioned modern progress events](docs/MODERN_PROGRESS.md)
- [Modern objective/gradient benchmark protocol](docs/MODERN_BENCHMARK.md)
- [Bounded-memory blockwise Gaussian primitives](docs/BLOCKWISE_GAUSSIAN.md)
- [Landmark-based Procrustes alignment](docs/PROCRUSTES_ALIGNMENT.md)
- [PCA of atlas-derived subject features](docs/ATLAS_PCA.md)
- [Desktop executable and installer architecture](docs/DESKTOP_DISTRIBUTION.md)
- [Windows one-directory freeze evidence](docs/WINDOWS_FREEZE_EVIDENCE.md)
- [Versioned desktop worker protocol](docs/DESKTOP_WORKER.md)
- [Desktop project-setup preview](docs/DESKTOP_PREVIEW.md)
- [Desktop reference prelaunch contract](docs/REFERENCE_PRELAUNCH.md)
- [Read-only reference preparation plan](docs/REFERENCE_PREPARATION_PLAN.md)
- [Saved reference preparation verification](docs/REFERENCE_PREPARATION_VERIFICATION.md)
- [Reference preparation-only approval](docs/REFERENCE_PREPARATION_APPROVAL.md)
- [Atomically prepare an approved reference plan](docs/REFERENCE_APPROVED_PREPARATION.md)
- [Approval-bound reference preparation worker](docs/REFERENCE_PREPARATION_WORKER.md)
- [Frozen approval-bound reference preparation worker](docs/FROZEN_REFERENCE_PREPARATION_WORKER.md)
- [Approval-bound reference preparation parent controller](docs/REFERENCE_PREPARATION_CONTROLLER.md)
- [Source preparation-worker parent-death evidence](docs/REFERENCE_PREPARATION_PARENT_DEATH.md)
- [Frozen preparation-worker parent-death evidence](docs/FROZEN_REFERENCE_PREPARATION_PARENT_DEATH.md)
- [Versioned reference worker lifecycle protocol](docs/REFERENCE_WORKER_PROTOCOL.md)
- [Nonnumerical reference worker pipe harness](docs/REFERENCE_WORKER_HARNESS.md)
- [Nonnumerical reference harness controller](docs/REFERENCE_HARNESS_CONTROLLER.md)
- [Frozen reference-worker parent-death evidence](docs/FROZEN_REFERENCE_PARENT_DEATH.md)
- [Open synthetic validation dataset](docs/SYNTHETIC_DATASET.md)
- [Synthetic numerical reference](reference/synthetic-v1/README.md)
- [Frozen Deformetrica CPU container](docs/CONTAINER_REFERENCE.md)
- [First-run workflow](docs/FIRST_RUN.md)
- [Result-report interpretation](docs/RESULT_REPORT.md)
- [Checkpoint, interruption, and resume](docs/RESUME_AND_RECOVERY.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Validation strategy](docs/VALIDATION_STRATEGY.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [AI usage](AI_USAGE.md)

## Data policy

Do not commit unpublished specimen meshes, sensitive metadata, manuscript
results, generated atlas outputs, or credentials. Test data must be synthetic,
public domain, or accompanied by a license that permits redistribution.

## License

DiffeoForge is released under the [MIT License](LICENSE). Third-party engines,
datasets, and dependencies retain their own licenses and must be documented
before redistribution.
