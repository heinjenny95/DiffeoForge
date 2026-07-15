# DiffeoForge

> [!WARNING]
> **Pre-alpha research software.** DiffeoForge is not yet validated for
> scientific production use. Its experimental reference backend can invoke an
> existing Deformetrica 4.3.0 installation, but installation and scientific
> equivalence are not yet automated or validated.

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

# Or prepare and execute a new run in one command:
diffeoforge run atlas.yaml --run-id experiment-002
```

Prepared run directories are write-once. DiffeoForge refuses to overwrite or
execute one a second time.

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
- contribution and AI-usage policies suitable for public research software.

It intentionally does **not** yet contain a new numerical atlas engine,
install or redistribute Deformetrica, provide a GUI or report generator, or
promise CPU/GPU equivalence. See the
[reference-backend documentation](docs/REFERENCE_BACKEND.md) for the exact
implemented boundary and current limitations.

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
- [Open synthetic validation dataset](docs/SYNTHETIC_DATASET.md)
- [Synthetic numerical reference](reference/synthetic-v1/README.md)
- [Frozen Deformetrica CPU container](docs/CONTAINER_REFERENCE.md)
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
