# v124 — screening-choice delivery

The verified Windows CPU private-alpha build is installed locally. Runtime freeze
source: `43acd39fc5b20bde6305c8a5b4c5a038173ec764`; the choice implementation is
`7b841b8`. Later delivery documentation does not change these installed bytes.

Verification completed:

- 54 focused pilot/retention/report/version/installer regressions passed, plus
  the additional numerical-panel case; a broader pilot/study/dialog set passed
  48 cases. The final choice/dialog set passed 11 cases after compact-layout
  correction. These sets overlap. Ruff and diff checks passed.
- Source and packaged choice/dialog bytecode show all five saved screens, require
  an explicit kept option, preserve the UI choice across redraws, and dispatch
  only that option. The themed 1000 × 720 view keeps the comparison in the
  existing scroll area without overlapping controls.
- Frozen GUI/startup, reference-worker, preparation-worker and parent-death
  boundary checks passed. Bundle, dependency metadata, SBOM and installer evidence
  were verified. No native scientific run was launched by these engineering checks.
- Fresh idle checks and a complete hash-verified previous-version backup preceded
  installation. All 2,837 runtime/freeze files and six evidence companions match
  the verified build. Installed version/startup and packaged UI probes passed.
- Read-only reopening of an existing eight-specimen queue through the installed
  compiled dialog restored the prior kept/discarded decisions, all five numerical
  rows and the three selectable kept options, with no default selection or worker.
  Prior review/sequence records and current project receipts remained unchanged.

See [scope and scientific limits](V124_SCREENING_CHOICE.md). Singleton numerical
order remains provisional; a new joint fit still needs its own all-specimen QC
and existing numerical gates. Existing scientific runs, settings and equations
were not changed, and no anatomical approval or PCA was created.

This is a private-alpha engineering delivery. No Drive upload, public release,
tag or merge occurred; the previously distributed package remains unchanged.
