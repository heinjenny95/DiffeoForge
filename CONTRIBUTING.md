# Contributing

DiffeoForge welcomes scientific, software, documentation, and usability
contributions. The project is pre-alpha, so proposals should begin with a GitHub
issue before large implementations are developed.

## Before opening an issue

Use the [structured issue chooser](https://github.com/heinjenny95/DiffeoForge/issues/new/choose)
so that a report enters the appropriate evidence path:

- **Bug report:** reproducible software behavior with a sanitized environment and
  synthetic or public reproduction data.
- **Feature or workflow request:** the user problem, desired workflow, and observable
  acceptance evidence before implementation details.
- **Scientific or numerical change:** rationale, references, controlled datasets,
  quantitative comparisons, tolerances, and limitations.
- **Usage or documentation question:** the intended research workflow, attempted
  instructions, and the exact decision or output that is unclear.

Do not attach private checkpoints or unpublished meshes. Checkpoints are Python
Pickles and must be treated as trusted-source-only artifacts.

## Local setup

```bash
git clone https://github.com/heinjenny95/DiffeoForge.git
cd DiffeoForge
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the checks used by continuous integration:

```bash
ruff check .
pytest
python -m build
```

## Pull requests

- Keep scientific and structural decisions explicit.
- Add or update tests for changed behavior.
- Document user-facing configuration changes.
- Do not mix private research data into code changes.
- Identify references and validation evidence for numerical changes.
- Describe material AI assistance according to [AI_USAGE.md](AI_USAGE.md).

The pull-request template is the minimum handoff contract. Release candidates
must additionally satisfy the evidence-based
[release checklist](docs/RELEASE_CHECKLIST.md).

## Scientific changes

Changes to objectives, kernels, integration, optimization, geometry handling,
defaults, or quality criteria require more than a passing unit test. A pull
request must state:

1. the mathematical or methodological rationale;
2. which reference implementation or publication was used;
3. which controlled datasets exercise the change;
4. quantitative expected and observed differences;
5. limitations and unsupported cases.

## Data contributions

Every contributed dataset must include provenance, authorship, and a license
that permits redistribution and automated testing. Do not submit unpublished
specimen data through issues or pull requests.
