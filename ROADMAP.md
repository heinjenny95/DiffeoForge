# Roadmap

This roadmap describes evidence gates rather than promised dates.

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
  - [x] Execute and review the frozen five-subject full-resolution Weevil
    screening study; record its non-converged result as inconclusive
  - [ ] Execute and assess the frozen ten-cycle Weevil continuation study
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
  Current self terms with dense value/gradient parity evidence
- [x] Add a versioned fresh-process multi-cycle optimizer benchmark with separate
  target-cache timing, exact work counters, result hashes, and strict verification
- [x] Freeze immutable subject-prefix by cycle-cap optimizer scaling designs before results
- [x] Execute and resume frozen optimizer scaling designs with strict raw-report verification
- [x] Expose versioned exact-count optimizer-study progress and read-only partial status
- [x] Replace ordinary rank-3 Gaussian differences with centered rank-2 matrix
  evaluation and protect values, gradients, translation stability, and workload accounting
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
- [ ] Add exact mid-run Modern optimizer checkpoints and crash recovery

## Milestone 3: Accessible application

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
- [ ] Add verified reference PC deformation meshes and registration-quality rendering
- [x] Define desktop executable/installer architecture and release gates
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
- [ ] Prospectively validate dataset-specific settings before any safe-preset claim
- [x] Pre-compute configured all-pairs and known-payload workload report
- [x] Versioned workflow-stage and committed optimizer-decision reporting
- [x] Fresh-process objective/gradient wall-time and sampled-RSS protocol
- [ ] Refine the staged calibration UX from the v44 weevil pilot observations
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
  - [ ] Make visual GPA-review navigation finite and unmistakable: show both
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
  - [ ] Revisit subject-tail/outlier stability and add regression tests for the
    full automatic-to-ambiguous-to-continued four-stage workflow
  - [x] Distinguish necessary biological deformation from pathological mapping:
    do not present raw deformation energy or surface-area change as universally
    negative; evaluate the fit improvement against smoothness, topology/Jacobian
    validity, and subject-tail failures, especially for high-disparity cohorts
  - [x] Let the researcher declare expected biological disparity and carry it
    into pilot range, scoring, explanations, and full-cohort confirmation
  - [ ] Add optional researcher-declared biological strata/extremes to the
    geometry-diverse pilot selection and its evidence report
  - [x] Separate deformation amplitude (`how different are the shapes?`) from
    deformation reach (`how broadly do regions move together?`); show exactly
    how both declarations change the pilot range and use them as transparent
    priors/tie-breakers rather than silently confirming the requested intent
  - [x] Replace the broad pre-run atlas ETA with a cohort- and hardware-bound
    estimator calibrated from the completed pilot runs and the selected control
    grid/timepoints, then update it from robust observed iteration timings
  - [x] Show two honest live estimates separately: `time to iteration cap` and a
    confidence-labelled `likely convergence window`; include startup/output cost,
    ignore warm-up outliers, and report when contention changes the observed rate
- [ ] Prospective multi-size end-to-end runtime and peak-memory calibration
- [ ] Cross-platform CPU distribution
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
