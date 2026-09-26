# Development continuity — v92 pilot appearance fix

Snapshot: 2026-09-26. This is a public, software-only continuation guide. Detailed
research results, local paths, account destinations and run identities belong in
the owner's private project handoff, not this repository.

## Product scope

DiffeoForge guides a reproducible Deformetrica workflow: input checks, documented
alignment, provisional parameter exploration, atlas execution, human visual QC,
and comparison of shape-space representations. It does not establish universally
correct parameters or interpret biology for the researcher. Deformetrica is the
default supported reference route; the Modern engine remains evidence-gated.

## Verified software baseline

v92 fixes a v91 appearance regression: the independent pilot explicitly
receives the existing main-window stylesheet, restoring the former fonts, cards
and green buttons without restoring modal ownership. Nine focused regressions,
Ruff, synthetic visual inspection and frozen-build checks passed. See
[v92 delivery and installation verification](V92_DELIVERY.md).

v91 source adds hidden PC-shooting launch, an independent minimizable pilot
window, contextual cost labels and persistent anatomy-first pilot decisions.
See [implementation and acceptance limits](V91_PILOT_REVIEW.md) and
[verified build and distribution](V91_DELIVERY.md).

The latest packaged and Drive-distributed application is **v92 / 0.0.0.dev92**,
built from `34dd5504d225d2af65b69752f9bbd14ba95586f5`. The current download
pointer was updated only after authenticated and anonymous downloads of all six
package files and both installer reconstructions matched the expected hashes.
The installed application is also **v92 / 0.0.0.dev92**, from the same runtime
commit. The owner cancelled the previously active pilot and closed the app;
cancellation and fresh application/WSL idle checks were verified before updating.
Installation followed a complete, hash-verified 2,688-file v91 backup. Registry
version, all 2,679 installed bundle files and installed startup smoke passed.
The 351 checked completed-run files remained unchanged. Both Drive READMEs now
record the verified installation, with IDs/sharing and installer bytes preserved.
No scientific run was started. Later documentation commits do not change the
binary's source identity.

For v91, 174 targeted regressions passed; after generalizing the dataset-specific
feature checks, all 49 affected study/dialog/lifecycle tests passed again.
Focused Ruff, layout, native minimize/restore with simulated progress, frozen
GUI/worker and build integrity checks passed. Actual cross-application foreground
acceptance remains open; no automatic anatomy detector is claimed. Broader legacy
desktop-test failures are disclosed in the implementation note.

- v90 adds searchable mesh selection with Add/Remove in pilot design. Required
  subjects occupy slots within the selected total; the remaining slots retain
  automatic coverage. Manual inclusion does not label a subject as a biological
  outlier. Optional CSV coverage is deduplicated, provenance is hash-bound and
  canonical input conversion/study reopening retain the selection.
- v89 adds normalized surface-shape coverage and a separate, bounded QC-concern
  recalibration route. Recorded concerns remain required; this is adaptive
  calibration with visual gates, not independent validation. A changed final
  configuration requires its own full-cohort atlas and QC, not replacement of
  individual old results.
- v88 fixes queued atlas-to-QC result handoff and exposes preparation progress.
  v87 fixes AFK/outward-search startup and visible failure handling. v86 addresses
  near-zero agreement-metric roundoff without relaxing hashes or changing scores.
- Earlier work includes opt-in AFK, display-only proxies, reduced-view landmark
  placement, synchronized mesh/landmark frames, natural rotation, overall
  Validation Lab progress, reference-engine defaults and shape-space reports.

For v90, 185 targeted tests and Ruff passed; synthetic GUI layout was inspected.
Frozen worker/startup and installer checks passed; 2,679 installed bundle files
were verified. This is not a fresh full-suite or native multiplatform acceptance
claim. No scientific run or anatomical approval was performed by the update.

## Completion policy

Follow the root `AGENTS.md`: each completed change includes a scoped GitHub push,
a verified English Project log entry, and maintenance of the latest tested Drive
installer. Track source, installed and distributed versions independently.
Documentation-only work does not create a new application version. Private-alpha
Drive distribution is not a GitHub Release, manuscript submission or authorization
to expose research data. Do not change existing sharing permissions implicitly.

The recorded v71 distribution lag was closed on 2026-09-25 using the unchanged
tested v90 installer. The complete four-part package, reconstruction and downloads
were verified before switching the existing current-README link; v71 remains
recoverable. See [v90 distribution evidence](V90_DRIVE_DELIVERY.md).

## Next work, in priority order

1. v92 installation and distribution are verified; v91 remains recoverable.
   Complete interactive minimize/focus acceptance across other applications;
   retain one pilot/controller and existing scientific evidence. Under the
   standing instruction in `AGENTS.md`, approval to develop a future version
   also authorizes its tested installation without another confirmation, after
   a backup and fresh idle check.
2. Complete native acceptance of the v90 selection workflow and the v89 QC return
   path, including reopening, cancellation, counts and clear next actions. Preserve
   human anatomical decisions and existing run evidence.
3. Continue the remaining usability/performance acceptance: concise main screens,
   immediate busy/error feedback, full completed-run loading time/peak memory and
   representative large-mesh viewer interaction. Do not weaken integrity checks.
4. Consolidate the four existing manuscript applications and independent review;
   reconcile historical linear-PCA and later same-atlas comparison evidence.
   Additional private development datasets are not automatically publishable case
   studies. No blanket rerun of existing atlases is required.
5. Close preprint acceptance gates with a public/synthetic end-to-end example,
   independent first-use and mathematical review, accurate claims, licensing and
   provenance. Then request the separate release/submission decisions.

Authoritative worklists and evidence:

- [Preprint readiness](PREPRINT_READINESS.md)
- [Roadmap](../ROADMAP.md)
- [Next-version scope](NEXT_VERSION_PLAN.md)
- [Manuscript outline](MANUSCRIPT_OUTLINE.md)
- [Annotated references](MANUSCRIPT_REFERENCES.md)
- [Parameter calibration](PARAMETER_CALIBRATION.md)
- [Build history](BUILD_HISTORY.md)
- [Release checklist](RELEASE_CHECKLIST.md)
- [Platform qualification](PLATFORM_COMPATIBILITY.md)

Roadmap checkboxes mix implemented substeps with still-open acceptance gates.
Read the evidence under each item; neither an old unchecked parent nor a passing
source test is enough to declare a feature unimplemented or fully qualified.

## Longer-term work (not all preprint prerequisites)

Native macOS/Linux distribution qualification, NVIDIA GPU qualification, actual
HPC/Apptainer deployment, Modern/reference numerical and performance comparison,
prospective pilot-selection and multiresolution sensitivity, calibrated runtime
and memory guidance, external usability and archived release/DOI work remain
evidence-gated. Do not equate hosted/offscreen CI with native interactive support,
or storage on a NAS/LSDF with remote computing.

## Starting a new task

Read the owner's latest private handoff, inspect current source/remote state,
then check only the live status needed for the next requested action. Historical
PIDs, elapsed-time estimates, old monitor messages and past installation approvals
are not current execution state. Do not restart jobs, reapprove QC or replay
finished build work just because it appears in an earlier transcript.
