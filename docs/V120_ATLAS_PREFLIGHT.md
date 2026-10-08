# v120 — reuse validated mesh checks during desktop atlas startup

The desktop project review already stored content-bound structural mesh checks,
but the reference execution worker opted into neither that cache nor mesh-level
progress. Atlas startup therefore repeated a full geometry inspection behind one
static message. Preparation then parsed the same inputs again.

The reference worker now uses the same config-local checkpoint directory as the
review. Each source mesh is freshly SHA256-hashed. Reuse requires the existing
JSON checkpoint contract, quality-definition version, matching byte count and
matching metadata/quality counts. Missing, changed or corrupt checks trigger the
ordinary inspection. Current quality gates are enforced on reused results too.
No pickle or arbitrary classes are loaded from these cache files.

The worker passes its exact preflight inventory into preparation. Preparation
checks current configuration, cohort, paths, sizes and fresh input hashes before
creating a destination; staged copies retain their independent hash checks.
Ordinary CLI/core callers still perform their default read-only inspection.
Resume-source verification is unchanged.

An additive `inspection` worker event reports hashing, new deep checking and
verified reuse/completion, with the current mesh and completed/total counts.
The parent validates phase, total, order and mesh boundaries. The Run card shows
these counts separately from optimizer iterations and explicitly says that
Deformetrica has not started. Cancellation is observed at inspection boundaries;
an individual uncached deep check must finish before the next boundary. A
cancelled preflight cannot prepare or execute a run.

Verification: 201 scoped Windows regressions passed, with one intentional
Qt-availability skip. Coverage includes fresh content invalidation, corrupt and
old-definition caches, current-policy rejection, cached worker handoff, stale
preparation refusal, unchanged staged scientific input bytes/parameters, safe
cancellation, strict event ordering and offscreen status rendering. Focused Ruff
and diff checks pass. The mandatory uncancelled frozen probe additionally reuses
valid saved checks, then rejects an invalid added mesh before preparation.

Build/installation evidence is separate. The owner has an active atlas, so no
installation may interrupt it. This change does not alter parameters, geometry,
alignment, QC approvals or scientific evidence, and does not start a new atlas.
