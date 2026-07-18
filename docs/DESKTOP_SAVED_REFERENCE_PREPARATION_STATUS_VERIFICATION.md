# Desktop verification of a saved reference preparation status

Status: **standalone read-only artifact verification; no project required**

The first DiffeoForge Desktop screen exposes the strict saved-status verifier
without requiring a mesh folder, project, configuration, approval, run,
container, or engine. This makes the methods artifact check available to users
who do not use a terminal.

## Inputs

The user selects:

1. one previously exported deterministic reference preparation status JSON;
   and
2. an independently recorded SHA-256 of that complete file.

The action remains disabled until both a path and exactly 64 hexadecimal hash
digits are present. The report is verified outside the Qt event loop by the
shared `verify_saved_reference_preparation_reconciliation` core. The GUI does
not reimplement hashing, strict JSON parsing, schema validation, canonical
serialization, or file-race detection.

## Bounded result

After success the desktop presents only the versioned verification evidence:

- report path, byte count, observed hash, schema, and recorded status;
- recorded run ID, approval hash, plan fingerprint, destination status,
  optional manifest hash, engine-start observation, and private-stage count;
- verifier schema and DiffeoForge version;
- completed-check count, deterministic representation, unchanged-file, and
  no-mutation statements; and
- the complete scientific boundary.

The display distinguishes successful artifact verification from the recorded
operational status. For example, an authentic `attention_required` report is a
successfully verified artifact but is not an authorization or recommendation.

## Stale-input and concurrency boundary

Only one desktop background operation is active at a time. Editing the report
path or hash immediately clears the prior result. If either input changes while
verification is running, the returned result or error is discarded. The
desktop additionally requires the returned absolute path and normalized
expected hash to match the exact worker inputs before displaying evidence.

## Explicit non-capabilities

This screen reads only the selected report. It does not inspect whether any
recorded path still exists and does not read current YAML, meshes, approvals,
destinations, private stages, processes, containers, or engines. It creates no
file and cannot repair, prepare, publish, recover, resume, cancel, or execute a
run. It does not establish parameter suitability, numerical validity,
convergence, registration quality, atlas quality, or biological validity.

The exact core contract and CLI equivalent are documented in
[Saved reference preparation status verification](REFERENCE_PREPARATION_RECONCILIATION_VERIFICATION.md).
