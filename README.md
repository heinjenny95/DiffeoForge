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
diffeoforge prepare atlas.yaml --run-id experiment-001
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
- explicit Deformetrica XML generation and native or Windows-to-WSL launchers;
- exact command, environment, lifecycle, convergence, result, and output
  inventories;
- an engine-independent architecture decision;
- an explicit scientific validation strategy;
- automated linting, tests, and package-build checks;
- a deterministic CC0 synthetic mesh cohort for public integration tests;
- versioned Deformetrica outputs and a tolerance-based reference comparator;
- a read-only environment doctor and transparent mesh-directory initializer;
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
  CLI and designed for reuse by the future desktop worker protocol, without
  invented percent-complete or ETA claims;
- an opt-in fresh-process objective/gradient benchmark with explicit subject
  selection, raw repeats, sampled process RSS, exact provenance, explicit
  standard/recompute blockwise measurement, and no extrapolation to full-cohort
  runtime;
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

The experimental modern path is a public CLI/application-service workflow, but
it is not yet the shared production backend behind a GUI and does not provide
checkpoint/resume. DiffeoForge also does **not** yet ship a desktop installer,
provide mesh-quality rendering or self-intersection detection, or promise CPU/GPU equivalence or
300-specimen production performance. See the [modern-workflow
documentation](docs/MODERN_WORKFLOW.md) and [reference-backend
documentation](docs/REFERENCE_BACKEND.md) for the exact boundaries.

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
```

For a configured blockwise plan, the microbenchmark can explicitly measure the
experimental recompute graph in separate fresh processes with
`--tile-autograd-strategy recompute`. This is a benchmark-only override, not a
`modern-run` setting, safe preset, peak-RAM claim, or automatic comparison.

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

A future full-factorial multi-tile study is specified in
[ADR 0004](docs/decisions/0004-prospective-multi-tile-matrix.md). It is not yet
implemented and will use new versioned contracts without changing existing
single-tile evidence.

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
