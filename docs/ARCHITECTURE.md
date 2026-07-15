# Architecture

Status: **draft**

## Layered design

```text
GUI and CLI
    |
Application service (validate, prepare, execute, run, status; resume/report future)
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

## Security and privacy boundary

The application is local-first. A run does not upload meshes, metadata, logs,
or telemetry unless a future feature obtains explicit user consent. Paths and
specimen identifiers must be reviewed before public diagnostic bundles are
created.

## Open questions

- exact mesh library for robust VTK/PLY/STL/OBJ inspection;
- modern numerical core: port, external library, or focused implementation;
- container strategy for Windows, Linux, and HPC;
- checkpoint compatibility across backend versions;
- portable path representation and privacy-preserving diagnostic exports;
- quantitative comparison formats and tolerance governance.
