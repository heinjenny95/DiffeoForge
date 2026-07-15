# DiffeoForge

> [!WARNING]
> **Pre-alpha research software.** DiffeoForge is not yet validated for
> scientific production use and does not currently estimate an atlas.

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

The command-line equivalent is expected to look like:

```bash
diffeoforge validate atlas.yaml
diffeoforge run atlas.yaml
diffeoforge report runs/example
```

Only `validate` exists in the current pre-alpha scaffold.

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

- a draft, machine-readable atlas configuration schema;
- a small CLI that validates that schema and input paths;
- an engine-independent architecture decision;
- an explicit scientific validation strategy;
- automated linting, tests, and package-build checks;
- contribution and AI-usage policies suitable for public research software.

It intentionally does **not** yet contain a numerical atlas implementation,
redistribute Deformetrica, or promise CPU/GPU equivalence.

## Developer quick start

DiffeoForge currently requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

diffeoforge validate examples/minimal-atlas.yaml --schema-only
pytest
ruff check .
```

The example configuration uses placeholder paths, so filesystem validation is
skipped with `--schema-only` until example meshes are added under a compatible
open-data license.

## Documentation

- [Project specification](docs/PROJECT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
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
