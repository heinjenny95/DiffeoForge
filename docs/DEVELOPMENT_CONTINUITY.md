# Development continuity — v116 live optimizer and continuation

Snapshot: 2026-10-07. This is a public, software-only continuation guide. Detailed
research results, local paths, account destinations and run identities belong in
the owner's private project handoff, not this repository.

Owner workflow update, 2026-10-01: installer uploads to Drive are now on explicit
request only. Automatic task-scoped GitHub and existing Project log updates
continue. Source, local installation and the last verified Drive package remain
separate states; retaining an older Drive package without a requested upload is
intentional, not an unfinished delivery. No rebuild or version bump is needed
for this documentation-only policy change. See the standing rules in `AGENTS.md`.

## Product scope

DiffeoForge guides a reproducible Deformetrica workflow: input checks, documented
alignment, provisional parameter exploration, atlas execution, human visual QC,
and comparison of shape-space representations. It does not establish universally
correct parameters or interpret biology for the researcher. Deformetrica is the
default supported reference route; the Modern engine remains evidence-gated.

## Current source work

v116 adds a lightweight live objective plot to full-reference execution and an
explicit +300-iteration successor for a completed capped gradient-ascent run.
The action is available in the Run card, QC footer and after reopening results;
source checkpoints/results/QC
are preserved. Launch request 0.3 retains 0.2 reading, and worker progress uses
the actual protected effective successor limit. See [scope and checks](V116_LIVE_OPTIMIZER_AND_CONTINUATION.md).
Native synthetic continuation restored iteration 4 and stopped at 131 under a
304 limit, with unchanged source bytes. Owner/scientific acceptance remains open.
The corrected frozen GUI/workers and installer are verified, but installation is
deferred while the owner app/full atlas are active. Installed dev115 is unchanged.
Build and installation evidence are tracked separately in [delivery](V116_DELIVERY.md).

v115 separates native optimizer checkpoints from complete mesh-trajectory output.
New preparations and immutable resume successors declare compact output scheduling
and protect the run-local adapter. Checkpoints replace atomically at the original
cadence; the unchanged final mesh export runs once with subject progress. Legacy
evidence and science settings are preserved. Actual reference-runtime synthetic
parameter arrays and final VTK hashes match the native schedule exactly; resume
restored the saved iteration. See [scope and limits](V115_COMPACT_REFERENCE_CHECKPOINTS.md).
Ninety-two scoped regressions, frozen packaging, full prior backup, fresh idle
checks and installed startup/file verification passed. Installed dev115 includes
the v114 desktop fix. Recorded owner run files remain unchanged; a verified
checkpoint can resume through a new compact-output successor. No private atlas
was started. See [local delivery](V115_DELIVERY.md). Native owner/scientific
acceptance remains open; Drive intentionally retains v98.

v114 removes repeated complete saved-pilot verification from GUI status updates
and native template-preview callbacks. Background status checks use an invalidated
UI cache; explicit pilot opening verifies again and supplies its snapshot to the
dialog. Project-switch/close callbacks cannot apply old results. Eighty-one scoped
regressions passed, with one dependency skip, plus read-only offscreen preview
profiling and Ruff. See [scope and limitations](V114_DESKTOP_RESPONSIVENESS.md).
Frozen packaging and installer verification passed; the v114 setup is ready.
Its standalone installation was deferred while the owner was working; this fix
is now installed as part of v115. See the historical [delivery state](V114_DELIVERY.md)
and current [v115 delivery](V115_DELIVERY.md). Native owner acceptance remains
open; no private fit or QC decision was performed. Drive retains v98.

v113 distinguishes the learned pilot seed from the original aligned cohort
template, retaining the same subjects through configuration review and atlas
preparation. Bound template/control hashes, original GPA evidence and cohort
counts are checked. Existing completed pilots need no rewrite or rerun; scientific
parameters and provisional warnings are unchanged. See
[scope](V113_PILOT_COHORT_HANDOFF.md). Sixty-four scoped regressions, frozen
packaging, full prior backup, fresh idle checks and installed startup/file
verification passed. See [delivery](V113_DELIVERY.md). Native owner/scientific
acceptance remains open; no atlas was started. Drive intentionally retains v98.

v112 fixes final-decision verification to restore atomic desktop preview-QC
records with their exact output binding. Existing completed studies reopen
unchanged. Completion runs in the background and hands parameters back to atlas
setup without a new fit or automatic atlas. Missing/changed review evidence stays
blocked; provisional warnings remain. See [scope](V112_PILOT_COMPLETION_HANDOFF.md).
Fifty scoped regressions, read-only completed-study verification, frozen packaging,
full backup, fresh idle checks and installed startup/file verification passed.
See [delivery](V112_DELIVERY.md). Native first-use/scientific acceptance remain open.

v111 separates native optimizer convergence, fixed-state integration and joint
anatomical QC. The default final check does not optimize; original failed receipts
keep their meaning. Explicit provisional completion of an approved, integration-
checked iteration-capped fit is disclosed throughout configuration/report/audit.
The full-cohort configuration restores the original project optimizer tolerance.
See [completion contract](V111_PILOT_COMPLETION.md). Frozen packaging, full prior backup, fresh idle checks, installation/startup
and installed-file/companion hashes passed. Saved pilot files are unchanged.
See [delivery evidence](V111_DELIVERY.md). Scientific and native owner acceptance
remain open; Drive distribution stays request-only.

v110 corrects the legacy declared Stage 4 queue verifier after an independent
qualification checkpoint is appended. Reopening, anatomical inspection and
resuming the existing declaration preserve all prior results and criteria.
Missing/reordered/extra candidates still fail verification. Viewer failures
replace stale preparation text. See [scope and checks](V110_SAVED_PILOT_COMPATIBILITY.md).
Frozen build, full prior backup, fresh idle checks, installation/startup and all
installed-file/companion checks passed; all recorded pilot files are unchanged.
See [delivery evidence](V110_DELIVERY.md). Native owner acceptance remains open.

v109 integrates specimen feedback, retained joint baselines, early Stage 2/3
screening, explicit blockers and reproducible audit export with a new final
qualification protocol. It continues one saved joint model with a tighter
optimizer criterion and separately shoots that immutable checkpoint on three
nested grids. Every specimen must pass; human anatomy approval is separate and
the new checkpoint needs its own review. Earlier trials and approvals are kept.
Clear progress and deduplicated attention notifications accompany the workflow.
See [method, acceptance and verification](PILOT_OVERHAUL_V109.md).
These are prospective engineering checks, not validated scientific thresholds
or a guarantee of optimal parameters. No private fit or QC decision was made.
Frozen packaging, full prior backup, fresh idle checks, installation/startup,
installed file/companion hashes and saved-pilot preservation passed; see
[delivery evidence](V109_DELIVERY.md). Drive intentionally retains v98.

v108 adds one explicit next-finer full-cohort comparison to a saved Stage 4,
preserving prior results and prospective numerical tolerances. It executes only
the added option and verifies its learned initialization and unchanged settings
on reopening. A nonconverged finer run cannot certify coarser stability. Human
anatomical QC stays separate. Earlier provisional choices remain disclosed;
later convergence does not prove a global optimum. See
[scope and checks](V108_FINER_TIMEPOINT_COMPARISON.md). Frozen packaging, full prior
backup, fresh idle checks, local installation/startup and all recorded saved pilot
files are verified; see [delivery evidence](V108_DELIVERY.md). Drive retains v98.
No private fit, stage selection or QC decision was performed.

v107 repairs retained-fit verification after several alternatives or continuation
attempts in one stage have been reviewed. The selected result's complete decision
history is validated separately; other reviews do not block it and withdrawal
still prevents reuse. Existing saved stages can use the unchanged keep action;
provisional warnings and strict Stage 4 checks persist. See
[scope and checks](V107_RETAINED_REVIEW_HISTORY.md). Frozen packaging, full backup,
fresh idle checks and installed startup/file verification are complete; all
recorded saved pilot files are unchanged. See [delivery evidence](V107_DELIVERY.md).
No private fit or stage selection was made. Drive intentionally retains v98.

v106 corrects the mandatory artifact count for cold frozen-singleton screening
and adds preparation-only retry for technical failures. Human decisions and
retained baselines remain bound; old failure evidence is preserved and verified.
See [behavior and verification scope](V106_SCREENING_RECOVERY.md). Verified build,
full backup, fresh idle checks and local installation/startup are complete. All
recorded saved pilot files remain unchanged; no private fit or retry was started.
See [separate delivery evidence](V106_DELIVERY.md). Drive intentionally retains v98.

v105 permits explicit provisional selection of a valid, whole-pilot visually
approved joint fit stopped only at the iteration limit in stages 1–3. Original
convergence evidence and automatic ranking remain unchanged. Exact retained
baselines carry the warning through stages 2/3; stage 4 remains strict. Reports
and exported provenance disclose earlier provisional decisions. See
[scope and synthetic checks](V105_PROVISIONAL_FIT_SELECTION.md).
Build, full prior-application backup, idle checks, safe installation and installed
startup/file verification are complete. Current saved pilot files remain unchanged.
See [separate delivery evidence](V105_DELIVERY.md). Runtime/build source remains
827b302; documentation commits do not require another build. Drive retains v98.

v104 offers persistent optional fixed-reference screening in stages 2/3: one or
two chosen specimens per option, a human decision before the next screen, then
only retained options in the joint comparison. Joint QC remains separate; the
approved baseline stays available. Stage 4 runs all timepoint options on the
complete pilot and records prospective engineering tolerances for the smallest
adequate next-finer comparison. Saved-series labels and reopening distinguish
individual approvals from current joint status. No private scientific run is
started. See [scope, compatibility and checks](V104_EARLY_PILOT_REVIEW.md).
Build, safe local installation and unchanged saved studies are verified; see
[separate delivery evidence](V104_DELIVERY.md). Prospective first-use, anatomical
acceptance and actual runtime savings remain open. Drive intentionally retains v98.

v103 retains exact approved joint fits across stages 2/3 and uses compatible
learned initialization for ordinary as well as adaptive transitions. Explicit
keep restores an already completed older comparison without refitting, modifying
old evidence or inventing QC. Stage 4 and full-cohort visual confirmation remain
required. See [scope and verification](V103_PILOT_TRANSITIONS.md). Build, safe
local installation and unchanged saved studies are verified; see
[separate delivery evidence](V103_DELIVERY.md). No private fit or parameter tuning
was started. Drive intentionally retains v98.

v102 releases the pilot controller on every terminal worker path, keeps errors
visible, and adds hash-bound Maybe / Plan B persistence, exact restoration and
fresh-review enforcement. Persisted specimen counts distinguish individual fits
from combined confirmation. Short alignment status and nearby PC-axis meshes
improve navigation; method labels explain the tangent approximation without
rewriting scientific evidence. See [scope and verification](V102_PILOT_WORKFLOW.md).
No private fit was started. Build and safe local installation passed; see
[separate delivery evidence](V102_DELIVERY.md). Saved approvals and fits remain
unchanged. Drive intentionally retains v98.

v101 retains approved individual fits while exhausted or rejected attempts enter
recorded broad-to-fine recovery using verified saved momentum fields. Explicit
saved-series selection avoids unintended resets. A separate denser common grid
starts with the difficult specimen and requires fresh approvals for the complete
pilot. No private fits are computed for this software update. See
[behavior, compatibility checks and limits](V101_PROGRESSIVE_SPECIMEN_FIT.md).
Build and safe local installation are verified; saved evidence remains unchanged.
See [separate runtime and delivery identities](V101_DELIVERY.md). Drive remains v98.


v100 removes the guided fit-search wall-clock limit and its minute selector.
Existing immutable studies and exhausted legacy budget files are accepted without
rewriting their evidence or resetting approved fits. Individual approval/rejection,
finite parameter alternatives, explicit cancellation, iteration limits and the
joint-confirmation requirements are unchanged. See [scope and compatibility checks](V100_NO_FIT_DEADLINE.md).
Build and safe local installation are verified; saved evidence and approvals
remain unchanged and reopen read-only. See [separate delivery identities](V100_DELIVERY.md).
Drive intentionally retains v98 under the request-only policy.


v99 contains native mesh filters in supervised hidden helper processes after a
reported Windows heap-corruption crash during individual-fit preparation.
Sequence children reuse exact parent working meshes and controls instead of
repeating reduction. Saved fitting evidence and scientific settings remain
unchanged. The precise native fault origin remains unproved; see
[containment, regression checks and limits](V99_MESH_FILTER_ISOLATION.md).
Build and local installation are verified; the saved rejected checkpoint was
reopened read-only after archiving its abandoned coordinator lock. See
[separate delivery identities and checks](V99_DELIVERY.md). Drive intentionally
retains v98 under the explicit-request policy. No private parameter-tuning or
new scientific run is started by this fix.

v98 replaces the guided first-stage grid with an explicit time-bounded **Find fit**
action: one attempt, then a visual checkpoint. Rejection tries the next parameters
for the same animal; approval starts the next specimen. A common deformation
basis is retained, with separate matching-weight trials for initialization.
All recorded individual
approvals precede a new shared-template original-target confirmation.
Scientific working targets remain distinct from display proxies; ranking measures
the worst specimen against original triangles. Human anatomy approval remains
required. See [implementation and verification](V98_FIT_SEARCH.md). Packaging,
installation and complete Drive distribution are verified separately; see
[delivery evidence](V98_DELIVERY.md). v97 remains recoverable.
Independent fields initialize the joint run; its results still
need new convergence evidence and whole-pilot visual approval.

v97 addresses slow and blocked pilot QC, overly strong numerical presentation,
and the loss of promising iteration-limited fits. Preview-based bulk approval,
completed-option inspection during calculation, source-bound display caches and
one-option warm continuation are implemented. Recorded rejection/acceptance now
affects automatic search centers; extra search is off by default. See
[behavior, verification and scientific limits](V97_PILOT_REVIEW.md). Built,
installed and Drive-distributed v97 are separately verified; see
[delivery evidence](V97_DELIVERY.md). A complete v96 backup/package remain recoverable.

v96 adds a bounded adaptive pilot search with compatible learned-state reuse,
per-specimen regression protection, persistent budgets and explicit stop reasons.
See [behavior and verification](V96_ADAPTIVE_PILOT.md). The v96 build, local
installation and complete Drive distribution are verified. A complete v95
installation backup and its Drive package remain recoverable. See the separate
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

The latest packaged, installed and Drive-distributed application is **v97 /
0.0.0.dev97**, built from `8350fc73489a143b124f4f0e605fc59b7c59dc83`.
110 scoped regressions, Ruff, synthetic UI and frozen packaging checks passed.
After confirmed closure, fresh idle checks and a verified 2,688-file v96 backup
preceded installation. Registry, startup and 2,679 bundle files passed; 3,630
checked study files remained unchanged. All six Drive files and both downloaded
installer reconstructions passed before updating the stable current README;
its authenticated/anonymous downloads and unchanged sharing were verified.
No private scientific fit or atlas was started. See [v97 delivery](V97_DELIVERY.md).

The historical v96 packaged, installed and distributed application was **v96 /
0.0.0.dev96**, built from `5a069968d5f8adee639ad60f347a9f6e4767b2fe`. Installation
on 2026-09-29 followed the owner's closure confirmation, fresh idle checks and
a complete 2,688-file v95 backup. Registry version, all 2,679 installed bundle
files and startup smoke passed; 2,101 checked completed-study files remained
unchanged. All six Drive package files and both installer reconstructions were
verified before the stable current README was updated. Stable IDs and sharing
remain unchanged; v95 remains recoverable. No private scientific run was started.
Later documentation commits do not change the runtime identity.
See [v96 delivery evidence](V96_DELIVERY.md).

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
a verified English Project log entry, and installer distribution only on explicit
owner request. Track source, installed and distributed versions independently.
Documentation-only work does not create a new application version. Private-alpha
Drive distribution is not a GitHub Release, manuscript submission or authorization
to expose research data. Do not change existing sharing permissions implicitly.

The recorded v71 distribution lag was closed on 2026-09-25 using the unchanged
tested v90 installer. The complete four-part package, reconstruction and downloads
were verified before switching the existing current-README link; v71 remains
recoverable. See [v90 distribution evidence](V90_DRIVE_DELIVERY.md).

## Next work, in priority order

1. Complete v98 packaging/distribution and assess the bounded search prospectively.
   Preserve v97 and all existing studies; no new private fit was run for development.
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
