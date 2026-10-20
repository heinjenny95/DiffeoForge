# Roadmap

This roadmap describes evidence gates rather than promised dates.

For the immediate publication priorities, use the
[preprint-readiness checklist](docs/PREPRINT_READINESS.md). It scopes the paper
to a guided, reproducible Deformetrica workflow and separates essential evidence
and usability work from larger Modern-engine/platform research. Its acceptance
items remain open until verified; planning does not implement them.

The [next development-version plan](docs/NEXT_VERSION_PLAN.md) sequences the
current UX work and explicitly plans the larger hardware, distribution and
scientific gates. Planning does not mark those gates complete.

## v138 implementation and remaining evidence

The owner authorized the current and older software backlog on 19 October 2026.
[v138 scope and reconciliation](docs/V138_DESKTOP_BACKLOG.md) records the completed
source work and remaining gates. Source checkboxes do not establish installed,
native scientific, external platform or independent usability acceptance. Current
scientific runs remain unchanged. No Linux/macOS or HPC test systems are available.

## Owner-requested cleanup

- [x] Apply the selected mesh view to all generated visualization media, including
  SD panels, maps and movies; keep the anatomical preview responsive, show PCA
  specimen IDs on hover, and offer individual/all side-by-side media with shared
  movie playback. The tested v143 Windows build is installed; independent first
  use remains separate. See [scope](docs/V143_VISUALIZATION_VIEWS.md) and
  [verified delivery](docs/V143_DELIVERY.md).

- [x] Add opt-in automatic process recording: active sections at 10×, long waits
  at 300×, MP4 after each completed computation and immediate follow-up recording.
  Capture only owned application UI, use bounded background encoding, declare
  capture gaps and recover sealed presentation fragments. Engineering checks
  and independent first-use acceptance are distinct. See
  [v130 behavior and limits](docs/V130_PROCESS_RECORDING.md).

- [ ] Remove the visible **Open demo · explore all steps with public examples**
  button (`open_demo_button`) and the demo/presentation mode, its other UI entry
  points, shortcuts and packaged assets. Owner request reaffirmed on 18 October
  2026: the button is still present in installed v130. Preserve real projects,
  results and engineering test fixtures. This task remains open until the button
  and demo entry points are removed, the change is tested and installed, and the
  installed UI is checked. v138 removes source/installer entry points and assets;
  the installed check waits for safe installation after active work ends.

## Atlas stopping and continuation

- [ ] On verified native convergence, prepare the configured PCA/method results
  and visualization assets during final export/postprocessing so the completed
  atlas opens with its results ready, rather than only point plots. Do not start
  this automatic preparation after an iteration cap, cancellation, interruption
  or failure. Keep computation off the GUI thread, show preparation progress and
  distinguish optimizer completion from results readiness. See
  [acceptance criteria](docs/PCA_VISUALIZATION_EXPORTS.md#prepare-results-before-converged-atlas-completion--pending).

- [x] When an atlas reaches its iteration limit, show how much its objective
  improved near the end and give a concise, explained recommendation beside
  **Continue +300 iterations**. Implemented in v138 source. Compare recent
  iteration windows (for example,
  the last 10 and 50), show absolute gains and relative changes with a declared
  denominator, and distinguish ongoing improvement, flattening and insufficient
  evidence. Account for sparse or rounded logs, continuation boundaries and
  non-monotonic/failed histories; do not infer a plateau from rounded equal values.
  Present the recommendation as a transparent heuristic, not predicted future
  gain, proven convergence or anatomical quality. Preserve native stopping/QC
  rules and explicit user-controlled continuation; never start extra iterations
  automatically. Keep analysis off the GUI thread and retain original run evidence.

## Longer-term UI customization — low priority

- [ ] Extend named mesh views to SD panels, displacement maps, movies and other
  method viewers. Offer a large anatomical preview, user-named views and optional
  focus/crop, then preview the selected export. Use one camera/scale across
  specimens and retain scientific coordinates; never infer anatomical names from
  arbitrary axes. v141 implements Stage 7's shared 2D/3D PCA glyph views first;
  other media still use their existing labelled cameras.

- [x] Add appearance settings with light/dark modes and user-selected colors.
  In particular, let users replace the current teal accent with an arbitrary
  color across navigation, buttons and other UI highlights. Apply the chosen
  theme consistently to owned dialogs, save the preference between sessions,
  and offer a reset to the default appearance. Keep text, focus, disabled controls
  and status messages legible across themes. Implemented in v138 source,
  with preview/cancel, persistence, reset and contrast checks.

## Pilot usability follow-up

- [x] Adopt a verified finer evaluation of the same saved field without another
  optimization: reuse checked grids, compute only the missing nested grid, bind
  a separate immutable candidate and require fresh anatomy review plus explicit
  provisional completion. See [v136 scope](docs/V136_RESOLUTION_ADOPTION.md).
  Native execution, tested packaging, installation and independent first use
  remain separate evidence gates.

- [x] Explain the selected final fit with separate shape, time-resolution and
  optimizer statuses; name the next time grid on the primary button and keep
  repeated warnings folded. Preserve scientific gates and reuse the verified
  assessment. See [v135 scope](docs/V135_PILOT_CHECK_EXPLANATION.md).
  Tested build, safe installation and independent first use are separate.

- [x] Keep the approved baseline and technical-screen retry visible after rejected
  options; provide one contextual Stage 4 next action and fold repeated check
  details. Preserve explicit selection, provisional warnings, fresh-fit QC and
  numerical completion gates. See [v134 scope](docs/V134_PILOT_NEXT_STEP.md).
  Tested build, installation and independent first use remain separate gates.

- [x] Make saved/current attempt identity explicit in fit inspection, reject
  self-file comparisons and stale deliveries, and label identical exports from
  separate runs. Retain the current geometry across reference changes. See
  [v133 scope and separate delivery gates](docs/V133_FIT_COMPARISON_IDENTITY.md).

- [x] Integrate relative better/worse/equal assessment directly into individual
  fit inspection, followed by explicit accept/reject. Ranking alone starts no
  attempt; closing without a final decision records nothing. Reuse the current
  mesh view and preserve the best after rejected improvements. See
  [v132 workflow](docs/V132_INLINE_FIT_INSPECTION.md). The tested version is
  installed; [build/installed verification](docs/V132_DELIVERY.md) and independent
  first use remain separate.
- [x] Add direct, synchronized better/worse comparison of individual fits and a
  persistent human-selected best starting point. Relative ranking guides bounded
  new attempts without approving anatomy or carrying fields across control bases.
  See [v131 behavior and boundaries](docs/V131_FIT_PREFERENCES.md).
- [x] Repair recording of the separate pilot/review windows and keep early
  landmark videos in the selected project before its config exists. Check the
  actual workflow window constructors and decoded media, not just generic dialogs.
  The tested v131 is installed; see [delivery verification](docs/V131_DELIVERY.md).
  Long real-study recording and independent first-use acceptance remain distinct.
  See [v131 recording repair](docs/V131_FIT_PREFERENCES.md#separate-window-recording-repair).

- [x] Make the early atlas checkpoint an explicit, default-off option. Allow
  checkpoint-bound continuation without inventing anatomical approval; preserve
  old pilot approvals, recorded rejections and final full-cohort QC. Replace stale
  live-activity text on stop. See [v128 scope](docs/V128_OPTIONAL_EARLY_REVIEW.md).

- [x] Repair the reopened control-density layout with proper widget ownership,
  scrollable optional controls and a persistent footer. Source visual checks
  cover pending/completed/density views at 850×650 and 1040×820. See
  [v129 scope and separate delivery gates](docs/V129_PILOT_AND_VISUALIZATION.md).
- [x] Guide new pilots through one fit, review, then a combined check; reuse
  freshly hashed full-detail/proxy geometry across views. Saved protocols and
  approvals remain preserved. See [v129](docs/V129_PILOT_AND_VISUALIZATION.md).
- [x] Propose starting atlas/initializer iteration headroom from selected pilot
  observations, retaining higher budgets and the native stopping criterion.
  Cap continuation remains explicit. See [policy and limits](docs/V129_PILOT_AND_VISUALIZATION.md).

- [x] Reopen a saved completed pilot from the parameter-page footer, keeping
  browsing separate from parameter application and exposing the optional density
  comparison. See [v127 access fix](docs/V127_SAVED_PILOT_ACCESS.md).

- [x] Add a chosen-fit-only, separate control-density comparison with a matched
  reference, two nested finer bases, fixed remaining settings, fresh result QC,
  manual selection and preserved source approvals. See
  [v126 scope and limits](docs/V126_CONTROL_DENSITY.md).

- [x] Rebuild the Stage 4 saved-fit chooser when the stage is ready, clear stale
  previous-stage IDs and label the retained result by its source stage. Preserve
  reviews, outputs and independent completion gates. See
  [v125 scope](docs/V125_SAVED_FIT_SELECTION.md).

- [x] Compare saved early-screen numbers, explicitly choose one kept option for
  the joint pilot test, and preserve all other screening approvals without
  launching them or calling them rejected. New joint results still need their
  own all-specimen QC. See [v124 scope](docs/V124_SCREENING_CHOICE.md).

- [x] Make the initial guided primary action use the existing one-specimen,
  one-attempt Find fit route and pause for human review. Remove the conflicting
  hidden Advanced-mode default and batch-start guidance; keep a full stage batch
  an explicit choice with its specimen/option workload shown before launch.
  Retain common-basis joint confirmation and all existing fit/anatomy gates.
  See [v129 implementation](docs/V129_PILOT_AND_VISUALIZATION.md) and
  [verified local delivery](docs/V129_DELIVERY.md); independent first use remains open.
- [ ] Qualify and repair cancellation end to end during native WSL execution and
  preparation: visible persistent cancellation state, verified command delivery,
  bounded backend exit, no subsequent candidate, checkpoint preservation and
  truthful terminal metadata. Include frozen Windows and backend shutdown-failure
  cases. An observed ineffective cancellation remains unresolved; a manual
  operational stop does not establish a software repair. v138 adds session
  supervision, launch-bound acknowledgements, bounded escalation and explicit
  missing-ack failure handling. Process-only checks pass; native scientific GPU
  and frozen Windows end-to-end qualification remain open.

- [ ] Profile and accelerate preparation before the pilot starts: aligned-cohort
  analysis, staged-plan construction, alignment/project preparation, verification
  and screening-target preparation. Reuse content/version/settings-bound mesh
  measurements, valid checks and approved transforms across steps; evaluate faster
  parsing/transformation/VTK writing and bounded CPU parallelism. Retain fresh
  hashes, stale-input rejection, coordinate precision, topology, scientific
  geometry and all fit/tolerance/anatomy gates; no silent decimation or skipped
  integrity checks. Verify cold/warm large-mesh timings, unchanged outputs,
  invalidation, progress and cancellation. v138 adds the scalar measurement
  cache and safe-boundary cancellation, with synthetic million-face cold/warm
  checks. Broader end-to-end preparation/RSS qualification remains open.

- [x] Check new screening approximations at every vertex/face centroid with
  component coverage, bounded resolution escalation and original fallback;
  retain cap tolerances and avoid redundant continuation after explicit tolerance
  stops. Fit/ranking/anatomy gates remain unchanged. See
  [v122 scope and limitations](docs/V122_PILOT_DETAIL_AND_CONTINUATION.md).

- [ ] Qualify mesh- and disparity-adaptive pilot execution with explicit screening
  fidelity, local-feature protection, stop-reason-aware continuation, held-out
  coverage and a quality-first baseline comparison. Existing adaptive/progressive
  features remain the baseline; no universal fit or speed claim is made. See
  [source audit and qualification plan](docs/PILOT_ROBUSTNESS_PLAN.md).

- [x] Reduce repetitive **Deformetrica still active** status messages from every
  30 seconds to every 3 minutes (180 seconds). Apply this interval only to the
  activity reminder; keep new iterations, phase changes, completion, errors and
  review requests visible immediately.
  Resource-only updates retain their 30-second cadence without reminder spam.
  See [v121 storage and activity](docs/V121_STORAGE_AND_ACTIVITY.md).

- [x] Reuse content-bound project mesh checks in desktop atlas startup, retain
  fresh hashes/current quality gates, and show actual per-mesh check counts.
  Avoid parsing the same preflight inventory again during preparation. See
  [v120 cached preflight](docs/V120_ATLAS_PREFLIGHT.md).

- [x] Remove the Windows atlas startup stall caused by an idle command pipe
  during native numerical-library loading. Require uncancelled frozen startup
  checks with stdin open, in addition to queued-cancellation checks. See
  [v119 startup correction](docs/V119_WORKER_STARTUP.md).

- [x] Retain compatible pilot momentum rows when initializing the full cohort;
  initialize remaining specimens on the fixed common basis and pause the joint
  atlas for source-bound early anatomical review. Offer a separate upgrade for
  completed legacy pilots. See [v118 scope and limits](docs/V118_PILOT_ATLAS_HANDOFF.md).
- [x] Add non-mutating **Show next specimen** navigation to full-atlas visual QC
  and emphasize reconstruction with a blue surface against orange original lines.
- [x] Reuse the atlas launcher-directory policy for PC-axis Shooting in deep
  project paths. See [v118 launch correction](docs/V118_PC_SHOOTING_LAUNCH.md).

- [x] Open a verified export-only successor for anatomical QC and momenta analysis
  with its protected original optimizer history and unchanged-state receipt.
  Display original history, saved iteration and export duration separately;
  reuse full verification only within one result-open operation. See
  [v117 import contract](docs/V117_EXPORT_ONLY_RESULT_IMPORT.md).

- [x] Provide a source support tool for final-export failures after a verified
  native stop: restore the unchanged saved state in a separate protected
  successor, reserve complete output space and skip further optimization.
  See [verification and limits](docs/REFERENCE_FINAL_EXPORT_RECOVERY.md).
- [x] Expose saved-state export recovery in the desktop (v138); prepare a separate
  unchanged-checkpoint successor, check storage and start only on explicit action.
- [x] Apply complete-flow storage planning to desktop cohorts below the production
  threshold, including resume, binary input/ASCII output expansion and the worker
  launch guard. See [v121 scope](docs/V121_STORAGE_AND_ACTIVITY.md).

- [x] Show a lightweight live objective history during full-reference atlas
  execution, with optional attachment/regularity curves, and offer an explicit
  +300-iteration immutable checkpoint successor after a capped run. Preserve
  source evidence/QC and distinguish iteration caps from tolerance/line-search
  stops. See [v116 scope and checks](docs/V116_LIVE_OPTIMIZER_AND_CONTINUATION.md).
  Native owner interaction and scientific acceptance remain open.

- [x] Separate compact native optimizer checkpoints from full mesh-trajectory
  exports in new and resumed reference runs. Replace checkpoints atomically,
  retain the unchanged final export with subject progress, and preserve legacy
  source evidence and scientific settings. See
  [v115 engineering verification and limits](docs/V115_COMPACT_REFERENCE_CHECKPOINTS.md).
  Full private-cohort runtime and scientific acceptance remain open.

- [x] Remove full saved-pilot verification from ordinary GUI refreshes and native
  template-preview callbacks. Resolve/check status in the background with a UI
  cache; explicitly opening a pilot still revalidates evidence. Discard old-project
  responses and preserve all scientific decisions. See
  [v114 checks and measured scope](docs/V114_DESKTOP_RESPONSIVENESS.md).
  Native interaction and broader large-mesh performance acceptance remain open.

- [x] Preserve the original aligned subject cohort when a learned pilot template
  initializes the full atlas. Verify original template/seed/control bindings,
  exclude only the documented template copy, and review the original GPA cohort
  without editing saved results. See [v113 correction](docs/V113_PILOT_COHORT_HANDOFF.md).

- [x] Offer an explicit **Reopen and refine saved pilot** action for completed
  and provisionally completed studies, alongside **Use saved parameters** and
  **Start new pilot**. Allow inspection and targeted continuation without
  restarting the entire search. Preserve the original results, review history,
  final selection and provisional warnings; record refinement as a linked
  successor with its own result-bound QC and applicable numerical checks.

- [x] Verify desktop preview QC from the atomic review journal when completing
  or reopening a saved pilot, preserve exact-result binding, and return directly
  to full atlas setup after background completion. No atlas automatically starts.
  See [v112 correction and checks](docs/V112_PILOT_COMPLETION_HANDOFF.md).

- [x] Separate native optimizer convergence, fixed-state integration and anatomy
  at pilot completion. Avoid default strict continuation, reuse bound evidence,
  and support an explicit provisional decision for an approved valid capped fit.
  Preserve failed historical receipts, warnings and original full-cohort optimizer
  tolerance. See [v111 contract](docs/V111_PILOT_COMPLETION.md). This supersedes
  historical final-stage stopping policies below; prospective scientific and
  native owner acceptance remain open.

- [x] Reopen legacy declared Stage 4 comparisons after appending a new independent
  qualification checkpoint. Preserve history/tolerances, exact queue coverage,
  source/seed integrity and resume the existing declaration. Viewer errors clear
  stale preparation status. See [v110 checks](docs/V110_SAVED_PILOT_COMPATIBILITY.md).

- [x] Integrate fit feedback, retained baselines, explicit blockers, complete audit
  export and independent optimizer/fixed-state integration qualification. Keep
  anatomy decisions and scientific validation separate. See
  [v109 scope and acceptance](docs/PILOT_OVERHAUL_V109.md).

- [x] Notify when a completed pilot step is waiting for human review, including
  while minimized or covered: a Windows notification or taskbar attention marker
  with the current stage and an action to open the pilot. Notify once per
  new review request, clear attention when acknowledged, avoid forced focus and
  intermediate-progress alerts, and preserve saved decisions. Source and offscreen
  regressions pass; native notification visibility under owner Windows settings
  and independent first-use acceptance remain open.

- [x] Extend a saved Stage 4 comparison by one next-finer full-cohort option when
  the initial options do not qualify. Preserve earlier results and prospective
  tolerances; require converged, valid full-cohort reference evidence and separate
  anatomical QC. See [v108 behavior and checks](docs/V108_FINER_TIMEPOINT_COMPARISON.md).

- [x] Verify a retained fit against its own bound review history when the same
  stage contains other reviewed alternatives or earlier attempts. Preserve later
  withdrawal, exact outputs, provisional warnings and Stage 4 requirements. See
  [v107 correction and regression scope](docs/V107_RETAINED_REVIEW_HISTORY.md).

- [x] Correct cold singleton screening preparation and provide targeted recovery
  for technical failures. Keep human rejections, accepted baselines and immutable
  attempt history distinct; verify the real preparation path rather than only a
  mocked controller. See [v106 behavior and checks](docs/V106_SCREENING_RECOVERY.md).
- [x] Allow explicit provisional selection of a valid whole-pilot visually
  approved joint fit stopped only at the iteration limit in stages 1–3. Preserve
  non-convergence, exact retained baselines and bound approvals; keep automatic
  selection and stage 4 strict. Disclose the decision in report/export provenance.
  See [v105 scope and checks](docs/V105_PROVISIONAL_FIT_SELECTION.md).
- [x] Make live pilot work and progress clear in one short status line: distinguish
  preparation, individual fitting, early option screening, combined confirmation,
  output verification and waiting for review, with a brief next action and folded
  technical details. Show optimizer iteration / cap, readable elapsed time and
  completed / total options separately from specimen approvals; do not present
  iteration / cap as a completion percentage or a reliable ETA. Keep option cards,
  phase summaries and buttons consistent with the active job: a running option
  must not also say `Ready to run`. Cover running, finalization, review, cancel,
  failure and reopening without resetting saved evidence. Implemented in v109;
  independent first-use acceptance remains open.
  - Label early single-specimen screening decisions separately from joint
    candidate completion. A retained baseline counts as an available joint
    result, not a new screening test. Identify the active stage, option, specimen
    and iteration / cap together, and show distinct screening and joint states
    on each option card with the next review or execution action.
- [x] Make saved-search choices readable: series label, saved time, current stage,
  individual approval count and separate joint-review status. Resume the chosen
  series at its verified current checkpoint; identify historical rejected trials
  explicitly. Do not confuse completed individual QC with joint-fit approval.
- [x] Offer early Stage 2/3 screening: compare each option on a selected difficult
  specimen, pause for visual feedback, and run the joint cohort comparison only
  for options the user elects to retain. An optional contrasting specimen can
  expose failures hidden by one screen; retain the preceding approved baseline.
  Stage 3 changes the data-fit/regularity balance and can change anatomical fit.
- [x] Bind screens to a documented fixed reference, settings and compatible
  initialization. Keep their QC scope separate from joint approval: screens are
  filters, not partial joint-atlas results. Recheck all subjects after joint
  optimization; persist the screening queue/decisions without an elapsed deadline.
- [x] Keep Stage 4 complete: run all timepoint options on the full pilot cohort.
  Recommend the smallest count agreeing with the next finer discretization in
  atlas geometry, objective and residuals within declared numerical tolerances;
  retain the accepted fit and report when no candidate qualifies. Single-subject
  screening must not truncate this comparison; speed alone cannot choose a winner.
- [x] Regression checks cover checkpoint restoration, history status,
  pause/reject/resume, cancellation, unchanged baseline and joint-QC gates.
  See [v104 behavior and verification](docs/V104_EARLY_PILOT_REVIEW.md).
- [ ] Assess actual runtime savings and first-use/anatomical acceptance prospectively.
  A fixed-reference screen cannot predict the shared-template joint optimum.

## Immediate follow-up from v92

- [x] Prevent duplicate deep input validation after an unchanged failure.
  A synthetic Qt reproduction shows that opening the failure dialog can move
  focus from an edited field and emit `editingFinished`, starting a second
  worker for the same failed signature without further user input. v93 starts
  checks only from an explicit button, prevents concurrent dispatch and never
  restarts after focus/input changes or stale results. Synthetic regressions
  cover failure-dialog focus, explicit retry and stale success/failure.
- [x] Validate landmark CSV structure and cohort filenames before expensive mesh
  topology inspection. In v92 an unrelated remembered CSV is rejected only
  after all meshes are inspected. v93 rejects incompatible or missing CSVs
  before mesh loading; regression spies verify no topology work is started.
- [x] Start with blank input paths and offer explicit restoration of every
  recorded path from the last project; loading history dispatches no validation.
  See [v93 implementation and verification](docs/V93_INPUT_VALIDATION.md).
- [x] Make the distinction between a loaded completed result and active
  **Data & Alignment** inputs explicit, and prevent an unintended new pilot
  using another project's retained inputs. Opening results currently updates
  the result view without replacing the setup form; this gap remains open.
  Preserve existing projects and require deliberate input selection.

- [x] Replace exact-folder completed-run opening with a searchable result library:
  discover nested version/selected-calibration runs in recent or explicitly added
  projects, remember locations, keep pilot/diagnostic fits optional, show project,
  specimen count and date, and allow local display names without moving folders.
  Bounded background scanning and full verification on explicit opening remain
  separate. See [v142 scope and delivery gates](docs/V142_RESULT_LIBRARY.md).

## Milestone 0: Public foundation

- [x] Public repository, license, and pre-alpha warning
- [x] Draft project scope and architecture decision
- [x] Versioned draft configuration schema
- [x] Minimal schema/path validation CLI
- [x] Initial automated tests and CI
- [x] Scientific validation plan
- [x] Openly licensed miniature surface dataset
- [x] Read-only environment doctor and transparent configuration initializer
- [x] Contribution issue templates and release checklist

## Milestone 1: Reproducible reference backend

- [x] Pinned CPU container for Deformetrica 4.3
- [x] Explicit XML generation from the public configuration
- [x] Immutable run directories and versioned manifests
- [x] VTK geometry preflight and mesh inventory
- [x] Local 8-subject CPU smoke test against the frozen environment
- [x] Checkpoint, resume, and failure-state handling
- [x] Self-contained HTML input-validation report
- [x] HTML convergence and result report
- [x] Reference results for the miniature dataset

## Milestone 2: Modern-engine feasibility

- [x] Evaluate a focused Deformetrica dependency port
- [x] Evaluate current PyTorch/KeOps-based libraries
- [x] Prototype only the deterministic 3D surface-atlas path
- [ ] Compare gradients, objectives, deformations, and performance
  - [x] Add a prospective fixed-reference qualification design that copies and
    hashes a completed Deformetrica template, its control points, pre-results
    geometry-diverse subjects, and their reference reconstructions
  - [x] Permit a Modern run to freeze template/control points, optimize momenta
    only, and use explicit blockwise recompute provenance
  - [x] Add common external surface-distance assessment with predeclared
    engineering non-inferiority gates; internal objectives are not compared as
    cross-engine equivalents
  - [x] Make the fixed-reference blockwise tile size an explicit prospective
    design input while retaining the established 64-row default
  - [x] Execute and review the frozen five-subject full-resolution Weevil
    screening study; record its non-converged result as inconclusive
  - [ ] Execute and assess the frozen ten-cycle Weevil continuation study
  - [x] Bind new fixed-reference continuation designs to parent/successor
    engine revisions and require successor-initial/parent-final objective parity
  - [x] Add deterministic recomputation and strict verification for published
    fixed-reference qualification assessments
  - [x] Include a normalized, strictly recomputed optimizer trajectory in new
    qualification assessments without changing the prospective registration gates
- [x] Record the engine decision in an ADR
- [x] Prototype landmark-based generalized Procrustes alignment
- [x] Integrate labelled landmarks and aligned mesh copies into modern run manifests
- [x] Prototype PCA for explicitly declared atlas-derived subject features
- [x] Integrate PCA evidence and tables into immutable atlas results
- [x] Connect mesh-folder preflight, initialization, modern optimization, and result bundles
- [x] Add PCA plots and PC deformation visualizations
- [x] Add deterministic input/output mesh-quality evidence and configurable gates
- [x] Add explicit blockwise Gaussian/Current/Varifold primitives with dense parity
- [x] Integrate explicit blockwise mode through the full atlas workflow,
  workload accounting, provenance, and fresh-process benchmark protocol
- [x] Prototype explicit tile recomputation with primitive/autograd parity and
  saved-tensor evidence
- [x] Carry tile recomputation through complete Subject/Atlas objectives and
  optimizer parity
- [x] Cache invariant fixed-target surface geometry and attachment self terms
  across optimizer evaluations with dense/blockwise value and gradient parity
- [x] Defer Armijo candidate gradients until objective acceptance and reuse the
  initial evaluation without changing optimizer decisions
- [x] Reuse the accepted objective/gradient across one-block cycle boundaries,
  eliminating one exact duplicate evaluation after every accepted cycle
- [x] Eliminate mirrored Gaussian tile evaluation in equal-tile blockwise
  Current and Varifold self terms with dense value/gradient parity evidence
- [x] Eliminate the redundant reverse surface-product multiplication for
  symmetric Current and Varifold off-diagonal self tiles
- [x] Reuse the already evaluated first RK2 shooting stage, reducing each
  step from six to four Gaussian calls with bit-identical trajectory evidence
- [x] Group recompute checkpoint administration by query tile for Gaussian
  convolution/x-gradient and Current/Varifold self/cross paths without changing tiles
- [x] Record a separate Modern engine implementation revision in new workflow
  and bundle evidence, and bind it prospectively in continuation plans
- [x] Add a versioned fresh-process multi-cycle optimizer benchmark with separate
  target-cache timing, exact work counters, result hashes, and strict verification
- [x] Bind new multi-cycle optimizer reports and prospective scaling designs to
  the Modern engine implementation while preserving legacy evidence verification
- [x] Add a strictly recomputed, non-selecting comparison artifact for compatible
  completed optimizer studies
- [x] Freeze immutable subject-prefix by cycle-cap optimizer scaling designs before results
- [x] Execute and resume frozen optimizer scaling designs with strict raw-report verification
- [x] Expose versioned exact-count optimizer-study progress and read-only partial status
- [x] Replace ordinary rank-3 Gaussian differences with centered rank-2 matrix
  evaluation and protect values, gradients, translation stability, and workload accounting
- [x] Remove repeated query/source mean reductions from every Gaussian tile by
  using one detached in-tile coordinate as the algebraically equivalent shared origin
- [x] Keep public tensor validation while removing repeated finite-value scans
  from already validated Gaussian calls inside shooting, flow, and attachment hot paths
- [x] Add an analytical recomputed Gaussian backward with first/second-derivative
  evidence and full-cohort sampled-memory measurement
- [x] Add an explicit fresh-process recompute benchmark path and spawn smoke evidence
- [x] Freeze immutable paired standard/recompute designs before observations
- [x] Execute/resume frozen designs with strict separate-report verification
- [x] Expose read-only partial status and dedicated completed-run verification
- [x] Emit versioned exact-count study progress without percentages or ETA
- [x] Specify backward-compatible prospective multi-tile matrix semantics
- [x] Run a prospective public standard/recompute engineering study without analysis
- [x] Run a prospective public multi-size/tile engineering study without analysis
- [x] Add a general hash-bound completed-run Modern continuation that preserves
  final template/control points/momenta, derives accepted starter steps, and
  verifies the successor's initial objective against its parent
- [x] Write and verify immutable, input-bound Modern state after every complete
  optimizer cycle
- [x] Create a guarded non-overwriting recovery successor from a verified
  abandoned Modern complete-cycle checkpoint
- [x] Serialize and strictly verify relative-objective baselines, reusable
  accepted gradients, and retained L-BFGS curvature pairs in checkpoint v0.2
- [x] Make completed-run continuation and abandoned-run recovery exact at
  committed cycle boundaries through configuration v0.5 and Engine 0.9
- [x] Bound new-run checkpoint storage to the latest verified five-cycle
  recovery point while preserving explicit all-cycle legacy behavior
- [x] Add deterministic parallel CPU execution across bounded subject batches,
  exact serial/parallel trajectory tests, provenance, and checkpoint binding in
  Engine 1.4
- [x] Prospectively screen Engine 1.4 subject-batch worker counts on the frozen
  real 16-subject cohort; two workers passed with an exact result and 23.77%
  lower median optimizer time
- [x] Confirm the selected two-worker candidate on all 236 subjects; exact
  result hashes, 21.55% lower optimizer time, and sampled peak RSS below the
  predeclared ceiling

## Milestone 3: Accessible application

- [x] **UX: less text, progressive disclosure.** Shorten the default copy across
  the guided workflow to a brief summary and the next action; move explanations,
  methods and advanced detail into collapsed, clearly labelled info boxes.
  Keep blocking errors, required decisions and essential warnings visible.
  Internal UI/regression review covers visible decisions and collapsed guidance;
  independent usability evaluation remains an open roadmap gate.
  - [ ] **High priority: further text reduction (reaffirmed 2026-09-26).** The default UI
    still feels overloaded, especially the "Project created successfully" card.
    Show a short status and clear next action; move full paths, provenance and
    routine technical notices into collapsed details. Remove repeated guidance
    across the workflow while keeping actionable warnings, blocking errors and
    required decisions visible. Verify the collapsed default on representative
    screens with user review; the first disclosure pass is not sufficient.
    The v83 project-created card now collapses paths/provenance; comparison
    numerical detail is also collapsed. Researcher review remains open.
    The alignment/GPA preview is another concrete acceptance case: users should
    not need to read its technical report to continue. Collapse fingerprints,
    scale ranges, centroid/RMS metrics, sensitivity-method detail and repeated
    read-only/reassurance paragraphs. Keep a short outcome, one clear next action,
    and concise actionable warnings or required decisions in the default view.
    Owner follow-up, 19 October 2026: continue simplifying the entire interface
    over time, including secondary windows and already-collapsible explanations.
    Merely moving a wall of text into a disclosure is insufficient. Rewrite copy
    in short, natural, concrete language; remove repetitive caveats, boilerplate
    and formulaic AI-sounding phrasing. Keep the current outcome and next action
    clear. Write routine technical detail and diagnostics to local log files in
    the background, with a discoverable way to open/search them when needed.
    Preserve actionable errors, essential warnings and required decisions in the
    UI. Review representative end-to-end screens with users. This expanded scope
    remains open backlog; no implementation or delivery date is claimed.
    Concrete owner example: cohort initialization repeats the same specimen and
    optimizer counters in **Verified live events** and the progress-bar caption.
    Show the phase, one compact specimen/iteration summary and the progress bar;
    keep the event history available in logs rather than duplicating the current
    status in adjacent labels. Check other workflow phases for the same repetition.
    The [19 October source audit](docs/UI_TEXT_AUDIT_2026-10-19.md) records 26
    concrete open items across pages 1–7 and supporting dialogs, with source
    locations, visibility/state, proposed reductions and checks against false
    positives. Prioritize repeated live counters/review badges and stale pilot
    instructions, then shorten expanded help and route diagnostics into logs.
    Audit complete; the listed UI changes remain unimplemented.
- [x] **Default new GUI projects to Deformetrica Reference.** Preselect the reference
  engine so the familiar guided parameter-calibration workflow is available by
  default. Keep Modern explicitly opt-in and labelled experimental; explain that
  its technical smoke pilot is not the staged parameter calibration. Preserve
  the recorded engine when opening or resuming existing projects; never silently
  convert them. Verify fresh-project defaults and both engine-selection paths.
  Implemented in v83; programmatic request defaults remain backward-compatible.
- [ ] **Immediate loading feedback / animated busy cursor.** Acknowledge slow
  actions as soon as clicked, before mesh loading or preparation begins: show an
  animated busy cursor and a short task-specific status or inline spinner. Bind
  the indication to real task state, not a cosmetic timer or invented progress;
  keep the UI responsive and prevent duplicate starts of the same action.
  Restore the cursor and controls on success, cancellation and failure, including
  overlapping jobs; show errors explicitly. Test delayed large-mesh loading,
  rejected clicks, repeated clicks and every exit path so a busy task cannot be
  mistaken for an unresponsive or broken button.
  V83 tracks main-window, pilot and Validation Lab workers, plus landmark/GPA
  and result-preview loaders, with window-scoped cursors and visible activity.
  Offscreen overlap/failure/cancellation/teardown checks pass; full native
  interaction and every synchronous action still need acceptance review.
- [ ] **Pilot window: allow minimization and prevent unwanted foreground activation.**
  v91 implements an independent modeless window and one retained controller;
  native minimize/restore and owner checks pass with simulated progress.
  Cross-application foreground observation remains an interactive acceptance
  check because the execution desktop does not expose a foreground handle.
  User-reported in v90 on 2026-09-25: the pilot-calibration window cannot be
  minimized, and the whole application reappears in the foreground when another
  window is opened, for example a folder in Windows File Explorer. Reproduce
  and diagnose the window behavior; the cause is not yet established.
  **Done when:** the pilot window can be minimized/restored normally, switching
  to another application keeps focus there, and DiffeoForge only returns to
  the foreground on explicit user activation. Verify native Windows behavior
  with an idle and a running pilot while preserving pilot state/progress and
  avoiding cancellation, restarts or duplicate jobs. This item records a bug;
  it does not claim a fix or authorize starting a scientific run.
- [x] **Pilot: opt-in AFK / overnight mode.** After each completed stage,
  automatically accept its eligible recommendation and start the next pilot
  stage without another click. Declare the permitted scope and provisional-choice
  policy before starting; log every automatic selection and its evidence.
  Pause clearly on hard failures or missing eligible recommendations; never
  invent visual-QC approvals or silently launch work beyond the agreed pilot.
  Support safe cancellation/resume and a concise return-to-desk summary; test
  normal progression, provisional choices, blocked stages and reopening.
  Unattended execution is not a guarantee of completion by the next morning.
- [x] **High priority: reduced display meshes in every renderer/viewer.** Use
  cached, detail-aware simplified display proxies by default, including
  settled views, original/reconstruction QC overlays, alignment, landmark and
  result/PC viewers; inventory every rendering path so none silently falls back
  to routine all-face rendering on large inputs. The updated
  [large-mesh viewer implementation](docs/LARGE_MESH_VIEWER.md) includes settled proxies.
  Keep original meshes, registrations, landmarks, numerical QC and analyses at
  their scientific resolution. Label display resolution and provide on-demand
  original-detail inspection; preserve exact original-surface landmark picking
  and prevent QC from claiming inspection of detail hidden by simplification.
  Bound background proxy generation, memory and stale-view work; verify
  responsiveness and preservation of relevant visible defects on large meshes.
- [x] Keep completed-run verification visible on the empty project-setup page
  for both engines; show a verifying button caption instead of idle input errors.
  Source correction only until included in a later installed build.
- [ ] Profile and reduce full completed-run reopening time and peak memory,
  separately from display-frame speed. The large installed-cohort check exposed
  a minutes-long pre-viewer verification phase. V83 streams QC mesh objects
  instead of retaining the cohort, and reports real verification stages and
  per-subject counts; aggregate metric arrays are still retained. Complete
  representative runtime/RAM profiling in addition to the regression-tested
  bounded-memory processing without weakening file verification or changing QC
  definitions. Do not skip scientific checks to make the viewer appear sooner.
  The v138 follow-up also flags repeated retained-stage/qualification verification
  and YAML/path work for operation-local profiling. GUI work remains asynchronous;
  no new end-to-end timing/RSS pass is claimed. See
  [follow-up audit](docs/V138_FOLLOWUP_AUDIT.md).

- [x] Adopt the Deformetrica-first product decision with an evidence-gated Modern engine
- [x] Extract strict landmark CSV handling from the Modern engine
- [x] Apply generalized Procrustes to content-addressed immutable mesh copies usable by
  Deformetrica or any future backend
- [x] Implement conservative observed-rate ETA arithmetic for Deformetrica iteration logs
- [x] Add interactive 3D homologous surface-landmark placement, correction,
  autosaved resume, and strict CSV output
- [x] Add researcher-selected landmark counts without an arbitrary ten-point cap
  and a draft-persisted optional automatic next-mesh transition
- [x] Add reviewed triangular PLY/OBJ/STL landmark and GPA import with
  byte-identical raw copies and canonical aligned VTK publication
- [x] Retain guided orthographic inspection as a separate deterministic preview
- [x] Connect hash-bound read-only Procrustes preview/approval to the guided
  desktop workflow
- [x] Expose explicit Procrustes application/settings and verify aligned-mesh evidence
  in desktop review
- [x] Connect supervised Deformetrica preparation, execution, and cancellation
- [x] Connect terminal interrupted/failed-run discovery and immutable checkpoint
  resume to the guided desktop workflow
- [x] Display observed progress and explicitly labelled ETA-to-iteration-cap
- [x] Import verified Deformetrica momenta into the shared PCA/result pipeline
- [x] **Automatically show PC-axis shapes with the PCA plots (owner request,
  2026-10-18).** Generate the -2 SD and +2 SD reconstructed shapes for the
  displayed PC axes automatically when PCA results become available, and show
  them directly below the corresponding plots without a separate generation
  button. Default coverage should include the existing PC1-PC3 axis views, with
  the mean shape available for comparison and clear axis/sign/SD labels. These
  views are a standard aid to anatomical and biological interpretation. Keep
  generation responsive with visible progress, reuse matching verified saved
  shapes on reopen, and preserve the source atlas, PCA and approvals. Implemented
  in v129; frozen/installed acceptance is tracked separately in its delivery.
- [x] **Export PCA media directly from DiffeoForge (owner request, 2026-10-18).**
  Add a Results & PCA export for mesh glyph plots at saved scores, comparable
  +/-2 SD extrema/mean heatmaps, and PC1-PC3 morphing movies from -2 SD through
  the mean to +2 SD. Movies should show six synchronized opposing perspectives
  (both sides of XY/XZ/YZ), with fixed cameras and shared colour scales. Produce
  a portable offline HTML gallery/ZIP with short English media headings, plus
  PNG/PDF figures and MP4 videos, for sharing with colleagues. Reuse verified
  saved evidence, validate native physical endpoints, keep progress responsive
  and preserve source runs/PCA/reviews. Keep technical logs, raw scientific files
  and identity keys outside the presentation package. See
  [media/export requirements](docs/PCA_VISUALIZATION_EXPORTS.md). Implemented
  in v129 with a separate left-rail Visualization page; installed acceptance
  remains a separate delivery gate.
- [x] **Interactive 3D PC1–PC3 morphospace in Step 7 Visualization** (owner request,
  2026-10-19; implemented in v138 source). Add a rotatable, pannable, zoomable view using
  existing verified PCA scores, with miniature specimen meshes as glyphs at their
  PC1/PC2/PC3 coordinates. Include axis/variance labels, specimen selection/hover,
  glyph-size control and reset view. Use consistent mesh orientation/scale and
  cached display proxies, with bounded background preparation so navigation stays
  responsive. Do not refit the atlas, recompute PCA or jitter score coordinates.
  Explain unavailable PC3 for lower-rank results. See
  [follow-up requirements](docs/PCA_VISUALIZATION_EXPORTS.md#deferred-follow-up--19-october-2026).
- [x] **Export every Step 7 medium individually in common formats** (owner
  request, 2026-10-19; implemented in v138 source). Provide direct saves for mesh-PCA plots,
  mean/SD panels, heatmaps and all available videos, plus a snapshot of the new
  3D viewer's current camera. Use PNG by default and optional JPEG for images,
  MP4 for videos; keep existing PDF files and the complete gallery ZIP available.
  Make the scope explicit (current item versus all media), reuse verified saved
  assets and check exported images/videos. Preserve axis labels, aspect ratio,
  units, color scales, source evidence and the media-only sharing boundary.
  Existing ZIP export is already implemented; these per-item controls and the 3D
  view are new work. See [scope](docs/PCA_VISUALIZATION_EXPORTS.md#deferred-follow-up--19-october-2026).
- [ ] Add verified reference PC deformation meshes and registration-quality rendering
- [x] Verify native PC Shooting's effective time grid and physical endpoint before
  selecting meshes. The inspected reference route can ignore the declared point
  count and select `t=0.9` as an endpoint. Repair selection with regression and
  installed checks; preserve existing evidence. See
  [derived-media requirements](docs/PCA_VISUALIZATION_EXPORTS.md) and
  [v129 native grid repair](docs/V129_PILOT_AND_VISUALIZATION.md).
- [x] Export the reference shape-space comparison as a PDF in the project folder
  in addition to the local HTML report; use a deterministic,
  provenance-bound destination, refuse silent overwrite, and expose both reports
  from the desktop result view.
- [x] Define desktop executable/installer architecture and release gates
- [x] Correct Validation Lab's scale-dependent small-triangle rejection and
  provide hash-bound post-processing recovery without rerunning completed atlases.
  See [evidence recovery](docs/reference-validation-evidence-recovery.md).
  Source implementation only; do not replace a running desktop executable.
- [x] Show actual study-wide Validation Lab progress, not only the current run.
  - [x] Separate original-start wall time (including labelled interruptions) from
    current-run elapsed time; retain it across reopening/resume.
  - [x] Use frozen-plan run positions, not successful-evaluation counts, for the
    current run number; retries must not double-count progress.
  - [x] Distinguish completed backends, verified evidence, pending/failed
    post-processing, execution failures, active and pending work. Recovery-needed
    atlases must not appear unstarted or falsely validated.
  - [x] Label overall execution progress and denominators, separating
    training/resampling from holdout and showing their combined workflow scope.
    Do not imply full validation while evidence/holdout gates remain unresolved,
    or equate an iteration-cap fraction with exact total progress or an ETA.
  - [x] Test evaluation failures, early convergence, retries, cancellation,
    reopening/resume and holdout transitions. Live runs remain untouched.
  - Legacy untimed ledgers explicitly show unavailable original timing; no
    file-mtime or resume-time substitution. Counts describe frozen run results,
    not equal-cost compute work. See the next-version plan for limitations.
- [x] Keep Validation Lab opening, preparation and mesh/workload preflight off
  the UI thread; refresh terminal evidence snapshots in the execution worker.
  - [x] Use an appropriate background worker/process, show preparation phases
    and progress, provide safe cancellation, and prevent duplicate starts.
  - [x] Preserve input/hash checks, geometry gates, the frozen study design,
    explicit start confirmation and completed immutable evidence.
  - [x] Test delayed preparation, responsive UI, cancellation, errors and repeated
    start clicks; a cancelled preparation must not launch a run afterward.
- [ ] Local graphical interface backed by the shared core
  - [x] First non-overwriting mesh-folder and project-setup slice
  - [x] Read-only effective-parameter and workload/preflight review
  - [x] Versioned Modern worker transport and nonpublishing cooperative cancellation
  - [x] Fail-closed parent controller with lifecycle, exit, and result verification
  - [x] Modern GUI start, exact live events, cooperative cancel, and verified result handoff
  - [x] Detailed verified Modern Atlas/PCA/QC summary and hash-bound artifact opening
  - [x] Clean-commit Windows one-directory engineering build with separate frozen worker
  - [x] Windows parent-death worker-tree termination and cross-platform pipe-EOF fallback
  - [x] Read-only exact-destination private-run discovery with process lease
  - [x] Transparent read-only private destination readiness in desktop step 3
  - [x] Hash-bound read-only external reference environment diagnosis
  - [x] Native read-only XY/XZ/YZ template wireframe preview
  - [x] Versioned hash-bound read-only reference prelaunch request
  - [x] Strict phase-dependent reference worker lifecycle protocol
  - [x] Real-pipe nonnumerical reference worker harness stopping before prepare
  - [x] Bounded nonnumerical reference harness parent controller with Windows Job containment
  - [x] Frozen sibling reference harness with mandatory v0.2 bundle evidence smoke
  - [x] Frozen reference-worker hard-parent-death Job containment evidence
  - [x] Versioned read-only reference preparation plan with exact XML parity
  - [x] Deterministic offline HTML review derived from the reference preparation plan
  - [x] Strict saved-plan/fingerprint/HTML read-only verification evidence
  - [x] Versioned preparation-only approval request and fresh current-plan verification
  - [x] Approval-aware exact private staging and atomic prepared-not-executed publication
  - [x] Approval-bound real-pipe preparation worker with strict prepared-not-executed evidence
  - [x] Bounded approval-bound preparation parent controller with Windows Job containment
  - [x] Source preparation-worker hard-parent-death Job evidence before request delivery
  - [x] Frozen approval-bound preparation sibling with mandatory v0.3 bundle smoke
  - [x] Frozen preparation-worker hard-parent-death Job evidence before request delivery
  - [x] Approval-bound read-only destination/private-stage reconciliation report
  - [x] Review-bound read-only reference preparation status in the desktop GUI
  - [x] Project-independent saved reference-status verification in the desktop GUI
  - [x] Exact non-overwriting saved-status verification-evidence export in CLI and desktop
  - [x] Exact non-overwriting plan/approval verification-evidence export in CLI
  - [x] Hash-bound source-level reference execution supervision and cancellation
  - [x] Add the reference execution sibling to the v0.4 freeze contract with
    queued-cancel and hard-parent-death gates
  - [ ] Record fresh clean-runner v0.4 freeze evidence and rebuild the installer
  - [x] Guided terminal reference-run discovery and immutable checkpoint resume
  - [x] Guarded desktop recovery for abandoned nonterminal reference runs
  - [ ] Native registration rendering
- [x] Parameter explanations and provenance-labelled exploratory starter profiles
- [x] Add hash-bound, non-executing dataset-specific calibration planning with
  3D feature-scale measurement, deterministic geometry-diverse pilot selection,
  staged candidates, explicit decision rules, and publication-oriented export
- [x] Automate approval-bound calibration candidate execution and verified
  residual/distortion/runtime evidence ingestion
- [x] V89: use normalized area-weighted surface-shape coverage for newly
  analyzed pilot cohorts, independently of triangle count or absolute size;
  retain legacy plan fingerprints and optional required-case declarations
- [x] V89: add a hash-bound QC-to-recalibration successor with all concerns,
  retained controls, 11 bounded candidates, mandatory stage visual review,
  and a new full-cohort atlas/QC requirement; never splice fits into old PCA
- [x] V90: searchable pilot-mesh dropdown with add/remove, mandatory inclusion
  within the pilot total, hash-bound provenance and retained CSV coverage support
- [ ] Prospectively evaluate shape-coverage selection on diverse large cohorts;
  synthetic invariance/local-feature tests do not guarantee anatomical coverage
- [ ] Prospectively validate dataset-specific settings before any safe-preset claim
- [x] Add a prospective multi-resolution mesh sensitivity workflow and guided
  evidence report: compare researcher-approved face-count levels without silent
  source-mesh modification; bind every derived mesh to its simplification
  provenance; assess atlas/template geometry, registration residuals, pairwise
  tangent distances, PCA subspace/scores, and reconstructed PC extremes; report
  the smallest tested resolution that meets predeclared stability tolerances, or
  state explicitly that no face-count recommendation is supported. v138 adds
  prospective frozen configurations and read-only assessment. Actual native
  researcher-approved study observations remain open.
- [x] Pre-compute configured all-pairs and known-payload workload report
- [x] Versioned workflow-stage and committed optimizer-decision reporting
- [x] Fresh-process objective/gradient wall-time and sampled-RSS protocol
- [ ] Refine the staged calibration UX from the v44 weevil pilot observations
  - [x] **Maybe / Plan B for individual fits (v102, 2026-10-02).**
    Add **Keep as Plan B** to retain a usable fallback while testing further
    settings for the same specimen. This is neither pass nor fail, does not
    advance the specimen or increase the approved count. Persist the exact bound
    attempt/specimen/series/model across reopening; provide direct comparison
    and **Use Plan B** if later attempts are worse, retaining all results and
    earlier approvals. Require explicit final human approval; never silently
    promote a fallback or transfer it across an incompatible basis. Implemented
    with hash-bound persistence, read-only comparison and fresh-review enforcement.
  - [x] **Visible specimen approval progress (v102, 2026-10-02).**
    Keep a compact count visible during individual fitting and review, e.g.
    **3 of 8 approved · 5 still to review**, plus **Specimen 4 of 8** and its name.
    Derive counts from persisted approvals for the current saved series/model,
    update after decisions and restore on reopen. Keep specimen progress separate
    from parameter-stage labels and later joint QC; completed computations and
    viewed previews do not count as approvals. Implemented; see
    [v102 scope and remaining acceptance](docs/V102_PILOT_WORKFLOW.md).
  - [x] Update the completed-run counter and candidate cards from the verified event
    ledger after every candidate instead of leaving `0 of 31`/`Ready to run` stale
    until a stage finishes
  - [x] Keep Automatic mode selected when the robustness gate finds an ambiguous
    result; show an explicit `Automatic selection paused` decision checkpoint
    instead of silently enabling Advanced mode
  - [x] Present one clearly labelled provisional recommendation with confidence,
    competing evidence, and the actions `Use provisionally`, `Compare options`,
    and `Collect more evidence`
  - [x] Never show `No relative comparison is available yet` after a completed
    comparison stage; display plain-language metric deltas and the actual
    fit-versus-regularity trade-off on every eligible candidate card
  - [x] Describe mixed pilot provenance accurately in the final review: do not
    label the whole study an `automatic provisional staged pilot` when some
    stages were explicit researcher selections; summarize each selection mode
  - [x] Prevent PCA scree-plot x-axis label overlap for dense component ranges:
    choose ticks from measured label widths, reserve the right edge, and add a
    67-subject/66-PC regression render at common Windows display scales
  - [x] Explain Visual QC as a plausibility/rejection gate rather than asking an
    untrained user to rank several visually acceptable registrations
  - [x] Make visual GPA-review navigation finite and unmistakable: show both
    `Mesh N of total` and the unique viewed count prominently, stop at the last
    mesh instead of silently wrapping to the first, announce `All meshes viewed`,
    and require an explicit action before starting the sequence again
  - [x] Turn full-cohort registration QC into a guided review: compute and rank
    subject-level residual outliers, open each original and reconstruction in a
    shared overlay, require pass/fail/uncertain decisions for the tail cases, and
    export the reviewed status instead of making users search a mesh dropdown
  - [x] Advance registration QC to the next unreviewed mesh after every decision,
    stop explicitly after the final decision instead of restarting, and atomically
    autosave/load a source-bound draft while retaining immutable snapshot export
  - [x] Place a mandatory Visual quality review step between atlas completion and
    Results & PCA: original/reconstruction overlays, per-specimen visual
    acknowledgement and explicit release after required flagged cases are resolved,
    including on reopen. Full-cohort review remains optional; unflagged/uninspected
    specimens stay unreviewed. Reuse the report's residual-screening rule and show
    each reason. Never substitute specimen filtering for review.
  - [ ] Revisit subject-tail/outlier stability and add regression tests for the
    full automatic-to-ambiguous-to-continued four-stage workflow
  - [x] Distinguish necessary biological deformation from pathological mapping:
    do not present raw deformation energy or surface-area change as universally
    negative; evaluate the fit improvement against smoothness, topology/Jacobian
    validity, and subject-tail failures, especially for high-disparity cohorts
  - [ ] **Further pilot recommendation audit (v90 feedback, 2026-09-25).**
    v91 implements neutral cost/area labels, anatomy-first ranking among
    accepted options, immediate hash-bound review persistence, per-specimen
    distances and dataset-specific feature checks with optional paired counts. Existing
    reconstruction identity and pooled-metric limitations were audited locally.
    Automatic feature detection and prospective independent anatomy validation
    remain open; see `docs/V91_PILOT_REVIEW.md`.
    Make deformation-cost badges neutral and consistent with the scoring policy:
    high-disparity scoring already omits energy, but lowest/highest-cost badges
    still assign favorable/caution tones. Interpret area change in context too.
    Investigate anatomical-fit adequacy before comparing cost or runtime, with
    explicit researcher review and separately validated automatic criteria;
    this does not mean removing backend regularization. Evaluate per-subject
    and local-feature evidence alongside pooled distances, including similar
    and highly disparate shapes. Show ambiguous/provisional recommendations
    clearly instead of implying an anatomically established best option.
    Audit existing disagreements between visual review and metric ranking on
    the same inputs/reconstructions, checking identity, display geometry and
    aggregation before attributing the cause to the metrics. Keep private case
    details local; do not retune weights solely to reproduce one preferred choice.
    **Done when:** discrepancies have a documented explanation, presentation
    matches the actual policy, and prospectively specified or independently
    reviewed checks address anatomically unacceptable fits hidden by favorable
    aggregate metrics. This is open design/validation work, not a scoring fix,
    universal parameter rule or authorization for new scientific runs.
  - [x] Let the researcher declare expected biological disparity and carry it
    into pilot range, scoring, explanations, and full-cohort confirmation
  - [ ] Add optional researcher-declared biological strata/extremes to the
    geometry-diverse pilot selection and its evidence report
  - [x] Separate deformation amplitude (`how different are the shapes?`) from
    deformation reach (`how broadly do regions move together?`); show exactly
    how both declarations change the pilot range and use them as transparent
    priors/tie-breakers rather than silently confirming the requested intent
  - [ ] Make calibration search-boundary handling explicit and adaptive:
    label every width unambiguously as attachment width, deformation width, or
    control-point spacing; detect when a selected attachment, deformation, or
    noise candidate is the minimum/maximum tested value; automatically extend
    the logarithmic grid by one or two outward candidates until the winner is
    interior or a predeclared safety/feasibility limit is reached; otherwise
    report `search range not bounded` instead of presenting an enclosed optimum.
    Add a regression case for the 236-subject Trochanter pilot, whose selected
    attachment width 0.258691 was the largest tested value and whose selected
    noise standard deviation 0.00808408 was the smallest tested value.
  - [x] Replace the broad pre-run atlas ETA with a cohort- and hardware-bound
    estimator calibrated from the completed pilot runs and the selected control
    grid/timepoints, then update it from robust observed iteration timings
  - [x] Show two honest live estimates separately: `time to iteration cap` and a
    confidence-labelled `likely convergence window`; include startup/output cost,
    ignore warm-up outliers, and report when contention changes the observed rate
- [ ] Prospective multi-size end-to-end runtime and peak-memory calibration
  - [x] Independently verify and retain the prospectively frozen 36-worker public
    float64 objective/gradient benchmark at 320 and 1,280 faces; all modes pass,
    with all time ranges and whole-worker RSS reported. This is not end-to-end
    atlas calibration; see `reference/public-engine-pair-v1/README.md`.
- [ ] Cross-platform CPU distribution
  - [ ] Isolate the Intel-Mac offscreen GUI segmentation fault in CI 34834843155;
    retain the failed observation and inspect native object/thread lifetimes,
    without skipping tests or claiming a fix from an unrelated numeric CPU pass
    - A local Windows full-suite process also aborted with a native access violation
      during desktop tests after the CPU-policy change. Hosted CI 34837396899
      passed all ten jobs; that green run did not resolve the native failure.
    - [x] Reproduce the Windows renderer-only lifetime crash and replace
      worker-owned QObject signals with a bounded Python mailbox/GUI timer;
      test owner destruction, cancellation and stale-frame rejection.
      Local full suite: 1,601 passed / seven skipped; final renderer repeat:
      200 passed / 2,000 explicit destruction cycles. CI 34839397593 passed all
      ten jobs, including all four GUI platforms. See `docs/DESKTOP_RENDER_LIFETIME.md`;
      the exact historical Intel-Mac cause remains unproven. A same-owner Windows
      build at `063143a` was subsequently installed and hash/startup-verified;
      interactive landmark and GPA viewer checks then passed on 15 September
      with six small synthetic meshes (rotation, view/specimen changes and
      close/reopen). No large-cohort performance claim follows from that smoke.
  - [x] Make the GPA viewer's in-canvas legend reflect the current overlay mode,
    selected surface and landmark visibility; test all eight layer combinations.
    This source correction is not yet in the installed `063143a` build.
  - [x] Observe 10k/100k/200k synthetic meshes across the three production canvas
    families, including proxy/original-detail gates, navigation, switching and
    active-render destruction. See `reference/desktop-viewer-matrix-v1` for all
    nine observations and their scope; full installed QC/PCA flows and large
    biological cohorts remain follow-up checks, not established by this matrix.
  - [x] Define installed-wheel GUI and public synthetic CPU compatibility matrix,
    exact provenance, three-platform numerical comparison and frozen tolerances;
    see `docs/PLATFORM_COMPATIBILITY.md` for observation status and boundaries
  - [x] Observe and independently verify the first Windows/Linux/Apple-Silicon
    CPU comparison and Windows/Linux/Apple-Silicon/Intel-Mac offscreen GUI matrix;
    retain exact public observations in `reference/platform-compatibility-v1`
  - [x] Diagnose the separate legacy reference-container convergence/residual
    mismatch (8/10 artifacts pass); retain frozen tolerances and reference bytes
    - CPU scalar-reduction sensitivity reproduced with unchanged geometry and
      static gradients; an instrumented AMD CI run passed 10/10 without a fix.
      Eight full paired atlases now confirm the public-fixture outcome: Intel
      Xeon 8573C AUTO passes only 8/10 twice, COMPATIBLE passes 10/10 exactly twice;
      AMD EPYC 7763 passes both modes twice. Retained bytes and comparisons are
      independently verified; see `reference/reference-cpu-full-pair-v1/README.md`.
  - [x] Implement the approved, process-scoped legacy-CPU COMPATIBLE setting;
    record the exact command and probe environment; prevent silent policy changes
    in prepared runs and checkpoint continuation. See `docs/REFERENCE_CPU_LAUNCH_POLICY.md`.
    Post-change default reference CI passes 10/10 byte-identically on observed
    Intel and AMD; independently verified evidence is retained in
    `reference/reference-cpu-policy-v1`. Broader cross-CPU qualification remains open.
  - [x] Fresh GitHub-hosted Windows one-directory engineering freeze, complete
    frozen-process smoke contract, and independently inspected evidence artifact
  - [x] Hash-bound, noninterpreting installed-distribution metadata and
    license-file evidence contract for later human review
  - [x] Deterministic CycloneDX 1.7 post-build SBOM contract with explicit
    incomplete-composition and nonapproval boundaries
  - [x] Exact source-hash-bound CycloneDX 1.7 generator and independent
    deterministic downloaded-evidence verifier
  - [x] Manual clean-runner integration with an exact six-file SBOM evidence
    boundary and accepted independent six-file observation
  - [x] Hash-bound, non-overwriting Windows installer script and deterministic
    non-executing compiler build plan
  - [x] Release-attestation- and Authenticode-bound Inno Setup toolchain
    authenticity observation with execution explicitly disabled
  - [x] Fail-closed evidence-only ephemeral-runner current-user install,
    installed-smoke, uninstall, and project-preservation workflow; first real
    observation and refined retained-integrity re-observation accepted
  - [x] Define fail-closed same-owner local private-alpha packaging and retained
    integrity verification; first exact handoff accepted
  - [ ] Reviewed release lock, SBOM, license clearance, signed installer, and
    clean-VM installation/uninstallation evidence
  - [ ] Separately gated Linux and macOS CPU distributions
- [ ] Validated NVIDIA GPU distribution
- [ ] Apptainer workflow for HPC environments

## Milestone 4: Scientific release

- [x] Frozen post-pilot finalist/resampling protocol, external surface metric,
  resumable Validation Lab execution, scoped report, and analytic
  known-correspondence generator
- [x] SHA-bound fixed-template registration workflow for untouched Validation
  Lab holdout subjects, with paired assessment and separate report
- [ ] Independent biological landmark validation and PCA subspace stability
- [ ] Multi-platform benchmark study
- [ ] External usability evaluation
- [ ] Complete user and methods documentation
- [ ] Archived release and DOI
- [ ] Software and/or methods-paper submission
