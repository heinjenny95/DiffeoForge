# Flagged-case visual QC: private alpha update

## Changes

- A dedicated visual quality-review step now precedes desktop result release.
  The required queue contains only residual-screened outliers; every specimen
  remains available for optional inspection and is retained in the atlas/PCA.
- Decisions require explicit acknowledgement that the displayed target and
  reconstruction were visually inspected. Uncertain or implausible decisions
  block release, including concerns raised on otherwise unflagged specimens.
- With no flagged cases, explicit result release is still required, but individual
  approvals are not. Cohorts smaller than four use an explained manual-review
  fallback. Changed evidence invalidates prior release; old decisions without
  visual acknowledgement do not bypass the gate.
- The same source update includes 3D Slicer JSON landmark import, Windows NAS
  alignment-staging compatibility, and a provenance-bound derivative PDF for
  completed shape-space comparisons. Original inputs and comparison bundles
  are preserved.

See [desktop workflow](DESKTOP_PREVIEW.md),
[landmark import and alignment](PROCRUSTES_ALIGNMENT.md), and
[comparison export](REFERENCE_PCA.md) for the detailed contracts.

## Local build and installation evidence

The private Windows build was produced from an isolated source snapshot, then
installed following the owner's separate explicit request. The previous app
was backed up; study data and the separate Deformetrica runtime were unchanged.

- Selected regression suite: **222 passed, 1 skipped**. The skip covered an
  inapplicable missing-PySide6 environment; this is not a full-suite claim.
- Affected QC/desktop/report lint checks and whitespace checks passed.
- Frozen GUI startup, synthetic workers, cancellation and Windows parent-death
  audits passed. Six embedded QC/GUI/report modules matched the source snapshot;
  synthetic tests exercised the actual frozen review/release gate.
- All **2,676 installed bundle files** matched the frozen inventory. Installed
  startup smoke passed, and the existing Desktop shortcut targets the new build.
- Private snapshot commit: `e9a4a0e07fe4fb65350350096bf7a746fb296230` (an isolated
  build-repository identifier, not a published source-branch commit).
- Installer SHA-256:
  `ec3230c77d9f76ff9d12fe4097609ffb3d0f57d808ce0bfb91a336189bd35202`.
- Main EXE SHA-256:
  `ea6e587a0163da243335584eaa7d24f0862bdb588c706cab5736798c2b21c3db`.

Detailed inventories, test results and installation logs are retained locally;
private data and installer binaries are not distributed through this note.
The source branch additionally includes this documentation, written after the
build; the build's historical provenance is not rewritten.

## Scientific and release limits

The relative screen flags residuals above Q3 + 1.5 IQR and can miss uniformly
poor fits. Visual plausibility is not biological validation. The reference
viewer uses a nearest-vertex p95 proxy, not the Current attachment objective
or a landmark-error measure; the Modern viewer uses attachment residuals.
This is a desktop workflow gate, not access control
over raw files. No new study atlas, pilot or Validation Lab run was started by
building or installing this update.

This is an unsigned private alpha, not a signed public release. Windows CPU
bundling does not replace the separately configured WSL reference runtime.

## AI assistance

OpenAI Codex materially assisted implementation, tests, documentation, build
verification and installation under Jenny Hein's direction. Human scientific
review and interpretation remain required, as described in [AI_USAGE.md](../AI_USAGE.md).
