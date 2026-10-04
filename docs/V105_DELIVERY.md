# v105 — verified build; safe installation pending

Software verification, 2026-10-04. Runtime source is
`827b302fdb797b716db2e04fe4699f080069f981`, on the established development branch.
Package and installer version are `0.0.0.dev105` / `v105 (Private Alpha)`.

The 64 scoped provisional-selection, retention, screening, study, desktop and
version cases passed, plus seven installer-contract cases. Ruff, compilation
and diff checks passed. An initial export failure exposed the missing schema
extension; this was corrected and covered by the final passing sets.

Frozen GUI and background-worker checks passed, including cancellation before
execution, preparation-only checks and narrowly scoped parent-death checks.
Dependency metadata, SBOM and exact installer-plan evidence were verified.
The private local installer was compiled and its evidence reverified. Its SHA-256:
`753c9f1f5c728553ad7340cd8d6892ab7e06e3d4ddcea59e7c8990ba23c32325`.

Local installation remains v104: the application is still open. Installation is
already authorized, but application backup, fresh idle checks, installation and
installed startup/file verification wait for safe closure. No process was stopped
to install this build. Do not report v105 as installed from build success.

No private fit, parameter tuning, atlas or anatomical decision was performed.
Prospective first-use/anatomical acceptance remains separate. Stage 4 still
requires convergence and numerical qualification; the whole cohort needs a new
atlas and QC. Drive distribution intentionally remains v98 by request-only policy.
No installer upload, tag, merge or release was made.
