# Architecture

Status: **draft**

## Layered design

```text
GUI and CLI
    |
Application service (validate, prepare, run, resume, report)
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

## Backend boundary

A backend will eventually implement operations comparable to:

```text
capabilities()
validate(config, dataset)
prepare(config, dataset, run_directory)
execute(run_directory, progress_callback)
resume(run_directory, progress_callback)
collect(run_directory)
```

The interface is deliberately defined by observable behavior and artifacts,
not by Deformetrica's XML structure. The legacy adapter may generate XML; a
modern backend does not need to.

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
- stable identifiers for configuration and run-manifest schemas.
