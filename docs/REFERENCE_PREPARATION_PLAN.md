# Read-only reference preparation plan

Status: **versioned exact-byte preview; no directory creation or engine launch**

`reference-plan` exposes the complete deterministic input to one future
immutable reference-run preparation before DiffeoForge creates an output root,
copies a mesh, writes XML, or starts a process.

```powershell
diffeoforge reference-plan atlas.yaml --run-id pilot-001
```

An explicit run ID is mandatory. Without additional options, the command prints
one ASCII-safe JSON document to stdout and writes no report or sidecar. It
normalizes the run ID with the same function used by `prepare`, resolves the
configured destination, and refuses to plan over an existing destination.

For a non-programmer review copy, explicitly choose a new HTML path:

```powershell
diffeoforge reference-plan atlas.yaml --run-id pilot-001 `
  --report review/pilot-001-preparation.html > review/pilot-001-preparation.json
```

JSON remains the only stdout payload; the written report path is announced on
stderr. The HTML is rendered from the same validated in-memory plan and is
deterministic: it has no timestamp, JavaScript, network call, or external asset.
It includes the plan identity and fingerprint, full input and protected-file
inventories, generated effective YAML and XML, backend constants, and exact
command vector. The report is created exclusively and never replaces an
existing file. Its parent directory is created when necessary.

## Versioned contents

Schema `reference-preparation-plan-v0.1.json` records:

- status `read_only_plan_not_prepared`;
- source-configuration path, byte count, and SHA-256;
- normalized run ID, resolved output root and destination, and confirmed absent
  destination;
- backend ID, contract version, fixed engine constants, DiffeoForge/Python/host
  identity, and native XML newline convention;
- the six planned run directories;
- template and subject source paths, staged relative paths, geometry metadata,
  byte counts, and SHA-256 hashes;
- the exact effective configuration;
- every future protected file in preparation order;
- exact UTF-8 content, byte count, and SHA-256 for effective YAML and all three
  Deformetrica XML files;
- source, byte count, and SHA-256 for every future copied file;
- total protected-file count and byte payload; and
- the exact backend command, working directory, and controlled environment that
  the prepared manifest would contain.

The plan and HTML report deliberately contain full local paths and specimen
filenames. Treat saved copies as private provenance unless those names have been
reviewed for publication.

## Shared exact-byte renderer

Planning and real preparation call the same pure XML renderer. The renderer uses
the previous `ElementTree.write` serialization behavior in memory, including the
host-native newline conversion. Regression hashes bind all three public example
XML files on Windows and POSIX. An integration test then calls the independent
atomic `prepare_run` path and requires every planned protected path, byte count,
SHA-256, generated UTF-8 payload, effective configuration, input record, and
command preview to match the real prepared run byte-for-byte.

This preserved the established reference XML contract during refactoring. A
seemingly equivalent `ElementTree.tostring` implementation was rejected during
development because it changed newline bytes and all three hashes on Windows.

## Read-only and race boundaries

The service validates and inspects all configured meshes but does not create the
configured output root. It binds the initial configuration bytes and rehashes the
configuration and every mesh after planning. A changed input, appearing
destination, invalid output-root type, unsupported reference configuration, or
schema-invalid plan fails closed. Tests compare the complete project tree before
and after repeated plans and require byte identity.

The plan is exact for the recorded host, configuration, input bytes, explicit run
ID, and current backend contract. It is not a prepared manifest: it contains no
creation timestamp, copied artifact, lifecycle event, or proof that sufficient
disk space remains at a later time.

## Scientific boundary

This command does not validate parameter choice, mesh homology, registration
quality, numerical convergence, engine equivalence, or biological
interpretation. It neither checks nor starts Docker or Deformetrica. After human
review, `diffeoforge prepare` remains a separate intentional mutation, and
`diffeoforge execute` remains the separate numerical action.
