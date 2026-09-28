# v95 — project-local setup checkpoints

Loading remembered project paths previously discarded completed intake checks
and GPA review state. The desktop now saves these in `.diffeoforge/checks` inside
the selected project, and explicitly loading recent paths verifies and restores
them in a background worker. Startup fields remain empty.

## Behavior

- Mesh inspection measurements are cached per file content, format and quality
  contract. SHA-256 checks include changes hidden by unchanged size/timestamps.
  Explicit deep validation computes missing/changed records only. Restoring paths
  never starts missing geometry checks or a GPA solver.
- GPA previews, transformations, settings and the actual recorded human review
  and approval persist. Changed cohort, meshes, landmarks or alignment settings
  invalidate the corresponding preview/approval. A software version change alone
  does not invalidate compatible records. Current quality gates are reapplied.
- Resume existing project uses its published configuration/aligned inputs without
  requiring the raw setup or GPA again. Desktop reference preflight also caches
  structural measurements; ordinary core/engine reads retain their checks.
- Checkpoints use bounded JSON, a fixed type allow-list, integrity digests and
  atomic writes. Corrupt/incompatible records cannot confer approval; foreign
  files are preserved. Write failures remain visible. Loading paths cannot carry
  an old in-memory approval into a different or modified project.
- Existing pilot manifests, event histories, completed candidate results and
  saved visual reviews are unchanged. This does not add mid-optimization resume
  for an interrupted candidate.

## Migration and boundaries

Earlier versions did not save all deep inspection measurements. A legacy project
may require one explicit check (or its first reference project review) to populate
that missing cache. Existing published GPA can still be used through Resume
existing project. No historical visual approval is inferred from convergence.
Moving a project to different absolute paths can require a new GPA review.

These engineering checkpoints are not independent scientific validation or run
evidence. No private mesh validation, pilot or atlas was launched for this update.

## Verification

110 focused tests passed across checkpoint persistence, input preflight, desktop
intake/history/review, preprocessing, project setup and reporting. Fifteen new
cases include real Qt restart/restore, stale callbacks, same-size/timestamp edits,
changed CSV/settings, corrupt caches, policy changes, absent approval and failed
writes. Two additional existing GPA/project-continuation tests passed.

One older broad desktop test fails at its advanced-parameter create-button
expectation; the identical assertion also fails with the unmodified v94 widget
module. It is not counted as passing or as new scientific qualification. Frozen
build and distribution evidence will be recorded separately after verification.
