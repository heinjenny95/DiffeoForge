# Development continuity — v96 adaptive pilot

Snapshot: 2026-09-28. This is a public, software-only continuation guide. Detailed
research results, local paths, account destinations and run identities belong in
the owner's private project handoff, not this repository.

## Product scope

DiffeoForge guides a reproducible Deformetrica workflow: input checks, documented
alignment, provisional parameter exploration, atlas execution, human visual QC,
and comparison of shape-space representations. It does not establish universally
correct parameters or interpret biology for the researcher. Deformetrica is the
default supported reference route; the Modern engine remains evidence-gated.

## Current source work

v96 adds a bounded adaptive pilot search with compatible learned-state reuse,
per-specimen regression protection, persistent budgets and explicit stop reasons.
See [behavior and verification](V96_ADAPTIVE_PILOT.md). The v96 build and complete
Drive distribution are verified. Local installation awaits safe closure of the
still-open main application; installed v95 remains intact. See the separate
[v96 delivery identities and checks](V96_DELIVERY.md). No new private scientific
run was started by the implementation.

v95 persists content-bound mesh inspections and recorded GPA review state in the
project folder. Explicit history loading verifies saved state without starting
missing computations; existing projects can resume their published alignment.
See [v95 behavior, migration and tests](V95_PROJECT_CHECKPOINTS.md). Build,
installation and complete Drive distribution are verified; see
[v95 delivery evidence](V95_DELIVERY.md).

v94 makes geometric pilot ranking fit-first and requires recorded acceptance of
every specimen before stage advancement. Local bounded refinement preserves old
runs and the complete cohort. See [v94 scope and limits](V94_SURFACE_FIT.md).
v94 was delivered before this checkpoint update. Its separate historical
verification remains in [v94 delivery evidence](V94_DELIVERY.md).

## Verified software baseline

v93 source starts with empty paths and offers **Load last project paths**.
**Run deep mesh validation** is the only preflight trigger; input/focus changes,
errors and stale results never restart it. Landmark CSV compatibility is checked
before mesh topology. All 178 scoped tests passed; 46 affected tests passed again
after final layout review. Ruff and synthetic visual inspection passed. Build,
installation and complete Drive distribution are verified. See
[v93 workflow and acceptance limits](V93_INPUT_VALIDATION.md).

v92 fixes a v91 appearance regression: the independent pilot explicitly
receives the existing main-window stylesheet, restoring the former fonts, cards
and green buttons without restoring modal ownership. Nine focused regressions,
Ruff, synthetic visual inspection and frozen-build checks passed. See
[v92 delivery and installation verification](V92_DELIVERY.md).

v91 source adds hidden PC-shooting launch, an independent minimizable pilot
window, contextual cost labels and persistent anatomy-first pilot decisions.
See [implementation and acceptance limits](V91_PILOT_REVIEW.md) and
[verified build and distribution](V91_DELIVERY.md).

The latest packaged and Drive-distributed application is **v96 / 0.0.0.dev96**,
built from `5a069968d5f8adee639ad60f347a9f6e4767b2fe`. Local installation is pending
safe closure of the main application, not new installation permission. Do not
interrupt a running job or unsaved work.

The latest verified installed application is **v95 / 0.0.0.dev95**, built from
`719e148e36f96d42194afa6cd4e0faf41b1b8283`.
Installation followed fresh idle checks and a complete 2,688-file v94 backup.
Registry version, all 2,679 installed bundle files and startup smoke passed;
2,101 checked current-study files remained unchanged. All six Drive files passed
authenticated and anonymous verification; both downloaded scripts reconstructed
the exact installer before the stable current README was updated. Its stable ID
and sharing remain unchanged. v94 remains recoverable. No private scientific run
was started. Later documentation commits do not change the runtime identity.
See [v95 delivery evidence](V95_DELIVERY.md).

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

1. v96 build/distribution are verified; install after safe closure, a fresh idle
   check and verified v95 backup. Then assess the adaptive search prospectively.
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
