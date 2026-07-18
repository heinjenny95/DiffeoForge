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
diffeoforge reference-plan atlas.yaml --run-id pilot-001
# Review the exact future run layout, generated XML, hashes, and command.
diffeoforge prepare atlas.yaml --run-id pilot-001
diffeoforge execute runs\pilot-001
diffeoforge report runs\pilot-001
```

`reference-plan` is a read-only JSON preview. It requires the same explicit run
ID that will later be supplied to `prepare`, inventories every selected mesh,
renders the exact future effective YAML and Deformetrica XML bytes in memory,
and confirms that the destination does not exist. It does not create the output
root or contact the configured launcher. See
[read-only reference preparation plan](REFERENCE_PREPARATION_PLAN.md).

Add an explicit new report path when a browser-readable review copy is useful:

```powershell
diffeoforge reference-plan atlas.yaml --run-id pilot-001 `
  --report pilot-001-preparation.html > pilot-001-preparation.json
```

The HTML is offline and self-contained, and it refuses to replace any existing
file. It contains full specimen paths and names, so review it before sharing.
Verify a saved pair later with:

```powershell
diffeoforge reference-plan-verify pilot-001-preparation.json `
  --report pilot-001-preparation.html
```

This checks the saved artifacts only; it does not claim the current meshes are
unchanged. An independently recorded `--expect-fingerprint` adds external
tamper binding. See
[saved reference preparation verification](REFERENCE_PREPARATION_VERIFICATION.md).

Optionally record that the exact reviewed plan — and only its immutable staging
step — was approved:

```powershell
diffeoforge reference-plan-approve atlas.yaml --run-id pilot-001 `
  --approve-fingerprint REVIEWED_SHA256 `
  --output pilot-001-approval.json

diffeoforge reference-plan-approval-verify pilot-001-approval.json `
  --current-config atlas.yaml
```

This request embeds the full plan, fresh-matches it to the copied fingerprint,
and permanently fixes engine authorization to false. It is not an identity or
signature record. See
[reference preparation-only approval](REFERENCE_PREPARATION_APPROVAL.md).

Before preparation, after a successful stopped-before-execution preparation,
or after an uncertain crash, classify only the exact approved paths without
changing them:

```powershell
diffeoforge reference-preparation-status pilot-001-approval.json `
  --current-config atlas.yaml `
  --expect-request-sha256 REVIEWED_REQUEST_SHA256 `
  --output pilot-001-preparation-status.json
```

The command can identify a verified published prepared run or a complete but
still unpublished private stage. It never publishes, deletes, resumes, or
repairs anything. See
[approval-bound reference preparation status](REFERENCE_PREPARATION_RECONCILIATION.md).

Independently hash and later verify the exact saved report without consulting
the current project or run:

```powershell
$statusHash = (Get-FileHash pilot-001-preparation-status.json -Algorithm SHA256).Hash
diffeoforge reference-preparation-status-verify `
  pilot-001-preparation-status.json `
  --expect-report-sha256 $statusHash `
  --output pilot-001-preparation-status-verification.json
```

Hash the complete verification-evidence file independently before archiving or
sharing it. Neither evidence creation nor verification reopens current project
or run state.

See [saved status verification](REFERENCE_PREPARATION_RECONCILIATION_VERIFICATION.md).

For the strict approval-aware mutation, independently record the complete
request SHA-256 printed by the verifier, then run:

```powershell
diffeoforge reference-prepare-approved pilot-001-approval.json `
  --current-config atlas.yaml `
  --expect-request-sha256 REVIEWED_REQUEST_SHA256 |
  Out-File -Encoding ascii pilot-001-preparation-evidence.json
```

This path fresh-replans, exact-matches private staged bytes, atomically publishes
without replacement, verifies the immutable run and empty output, and returns
before any engine execution. The generic `prepare` command does not enforce an
approval. See
[atomically prepare an approved reference plan](REFERENCE_APPROVED_PREPARATION.md).

For a cohort of hundreds of specimens, start with a small representative pilot
and inspect the objective curves, lifecycle, evidence checks, and output
inventory before committing the full dataset. The result report deliberately
distinguishes a successful backend exit from demonstrated convergence and from
scientific validity. See [result-report interpretation](RESULT_REPORT.md).
For long runs, review the checkpoint save interval and the explicit
[interruption and resume workflow](RESUME_AND_RECOVERY.md) before starting.
Resource estimation and progress reporting remain separate roadmap items.
