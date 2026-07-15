# Architecture

Status: **draft**

## Layered design

```text
GUI and CLI
    |
Application service (validate, prepare, execute, run, recover, resume, status, report)
    |
Versioned configuration and run-manifest contracts
    |
Backend interface
    +-- Deformetrica reference backend
    +-- Modern LDDMM backend (future, validation required)
```

The GUI must not implement separate scientific behavior. It edits the same
configuration schema and calls the same application service as the CLI.

## Configuration as a public contract

The user-facing YAML is validated against a versioned JSON Schema. This allows
the CLI, GUI, documentation, and future workflow integrations to share field
names, types, allowed values, and descriptions.

The YAML is not passed directly to a numerical engine. A backend adapter
translates the validated configuration into engine-specific input and records
the fully effective configuration in the run directory.

## Prepared-run boundary

Preparation is atomic: files are first assembled in a temporary directory and
renamed to the final run ID only after geometry inspection, input copying, XML
generation, hashing, and manifest-schema validation all succeed. Preparation
never overwrites an existing run ID.

`manifest.json` and its SHA-256 sidecar describe all evidence known before
execution. Staged input, source/effective configuration, and generated XML are
protected by hashes. `events.jsonl` records the append-only lifecycle.
Execution verifies this evidence and requires an empty output directory before
starting the backend exactly once. `result.json`, `logs/convergence.csv`, and
`output-inventory.json` record the terminal outcome without rewriting the
prepared manifest.

`result-report.html` is a derived, regenerable view of those evidence files.
It is not a substitute for them and is not included in the numerical output
inventory. Report generation revalidates the prepared-manifest digest and
checks consistency among the terminal event, result, convergence-row count,
and output inventory. The report is self-contained and performs no network
requests.

## Interruption and successor boundary

A clean keyboard interrupt is finalized as a terminal `interrupted` state with
partial logs, convergence history, output inventory, and checkpoint evidence. An
unclean `started` state can be finalized only by an explicit recovery operation
after the caller confirms that the numerical process has stopped.

Resume does not reopen the source run. It atomically prepares an immutable
successor containing a versioned `resume/resume.json` provenance record and a
protected copy of the source checkpoint. The execution copy is placed under the
new run's `output/` only after protected-artifact and environment verification.
The adapter treats the checkpoint as opaque bytes; only the pinned backend may
deserialize it.

## Backend boundary

The backend contract is defined by operations comparable to:

```text
capabilities()
validate(config, dataset)
prepare(config, dataset, run_directory)
execute(run_directory, progress_callback)
resume(run_directory, progress_callback)
collect(run_directory)
```

The interface is deliberately defined by observable behavior and artifacts,
not by Deformetrica's XML structure. The current reference adapter generates
three XML files and invokes an externally supplied Deformetrica 4.3.0
executable. A modern backend does not need to use XML or Python 3.8.

The experimental modern-engine primitives are not a backend yet. Dense PyTorch
CPU/float64 is the inspectable correctness baseline selected by ADR 0002. An
optimized kernel or GPU path must reproduce that baseline before it can sit
behind the backend interface.

## Security and privacy boundary

The application is local-first. A run does not upload meshes, metadata, logs,
or telemetry unless a future feature obtains explicit user consent. Paths and
specimen identifiers must be reviewed before public diagnostic bundles are
created.

## Open questions

- exact mesh library for robust VTK/PLY/STL/OBJ inspection;
- container strategy for Windows, Linux, and HPC;
- validation of checkpoint compatibility beyond the identical frozen backend;
- portable path representation and privacy-preserving diagnostic exports;
- quantitative comparison formats and tolerance governance.
