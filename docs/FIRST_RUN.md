# First-run workflow

Status: **pre-alpha usability workflow; not validated for scientific production**

The first-run commands turn a mesh directory into an explicit configuration and
a reviewable input report without requiring Python, XML, or notebook editing.
They use the same public core that a future graphical interface will call.

## 1. Diagnose the computer

From the intended project directory, run:

```powershell
diffeoforge doctor
```

`doctor` is read-only. It checks the host Python version, operating system,
logical CPU count, physical memory, workspace access, free disk space, Docker
command, Docker service, and pinned reference-image availability. Each check is
reported as `PASS`, `WARN`, `FAIL`, or `SKIP`.

A warning does not block the command. A failed check produces overall status
`blocked` and exit code 1. Machine-readable output is available with:

```powershell
diffeoforge doctor --json
```

The command does not install software, start Docker, download an image, or run
Deformetrica. This keeps diagnosis separate from state-changing setup.

## 2. Initialize a mesh directory

The shortest non-interactive command is:

```powershell
diffeoforge init "C:\path\to\meshes" --units millimeter
```

When `--units` is omitted in an interactive terminal, DiffeoForge asks for it.
Units are never silently inferred from coordinates. The template is
auto-detected only when exactly one file is literally named `template.vtk`
(case-insensitive). Otherwise pass it explicitly:

```powershell
diffeoforge init "C:\path\to\meshes" `
  --template "initial-template.vtk" `
  --units millimeter `
  --config "atlas.yaml"
```

The command validates every selected mesh before writing anything. On success
it creates:

- `atlas.yaml`: the complete, schema-valid configuration;
- `atlas.preflight.html`: a self-contained input and parameter report.

Existing files are never replaced unless `--force` is explicitly supplied,
and even then only files carrying the DiffeoForge generator marker qualify.
Unrelated YAML or HTML files are protected from replacement.
The default subject pattern is `*.vtk`; the resolved template is excluded from
the subject list. Use `--subject-pattern` when a directory contains unrelated
VTK files.

## Exploratory starting values

Four model parameters cannot be inferred scientifically from file validity.
When they are not supplied, `init` creates clearly labelled exploratory values
from the template bounding-box diagonal:

| Parameter | Exploratory ratio |
| --- | ---: |
| attachment kernel width | 0.10 |
| deformation kernel width | 0.15 |
| initial control-point spacing | 0.15 |
| noise standard deviation | 0.025 |

These ratios are reproducible initialization rules, not validated defaults.
The generated YAML header identifies every derived parameter, its exact value,
and its ratio. Override any or all of them explicitly:

```powershell
diffeoforge init "C:\path\to\meshes" `
  --units millimeter `
  --attachment-kernel-width 0.45 `
  --deformation-kernel-width 0.60 `
  --control-point-spacing 0.60 `
  --noise-std 0.10
```

## 3. Regenerate or relocate the report

Validation can write a new report without running the atlas:

```powershell
diffeoforge validate atlas.yaml --report
diffeoforge validate atlas.yaml --report reports/input-review.html
```

Use `--force-report` only when deliberate replacement of a recognized
DiffeoForge report is intended. The report
contains:

- resolved input and template paths;
- subject count, total input size, units, and geometry ranges;
- parameter-to-template-size ratios;
- review notices for unitless coordinates, heterogeneous resolution or scale,
  and cohorts larger than 250 subjects;
- one row per mesh with points, triangles, encoding, scale, bytes, and SHA-256;
- the exact effective YAML configuration;
- an explicit scientific boundary statement.

The HTML contains no JavaScript, network calls, or external assets. Passing it
means the declared files and supported geometry are internally readable. It
does not validate biological interpretation, registration, parameter choice,
or equivalence between numerical engines.

## 4. Review before computation

After reviewing `atlas.yaml` and the report:

```powershell
diffeoforge prepare atlas.yaml --run-id pilot-001
diffeoforge execute runs\pilot-001
diffeoforge report runs\pilot-001
```

For a cohort of hundreds of specimens, start with a small representative pilot
and inspect the objective curves, lifecycle, evidence checks, and output
inventory before committing the full dataset. The result report deliberately
distinguishes a successful backend exit from demonstrated convergence and from
scientific validity. See [result-report interpretation](RESULT_REPORT.md).
Resource estimation, progress reporting, and checkpoint/resume support remain
separate roadmap items.
