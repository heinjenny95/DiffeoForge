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
- [x] Add an explicit fresh-process recompute benchmark path and spawn smoke evidence
- [x] Freeze immutable paired standard/recompute designs before observations
- [x] Execute/resume frozen designs with strict separate-report verification
- [x] Expose read-only partial status and dedicated completed-run verification
- [x] Emit versioned exact-count study progress without percentages or ETA
- [x] Specify backward-compatible prospective multi-tile matrix semantics
- [ ] Run a prospective standard/recompute study before public integration
- [ ] Run a prospective multi-size/tile blockwise performance study

## Milestone 3: Accessible application

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
  - [ ] User-approved private-stage mutation, reference supervision, and native mesh rendering
- [ ] Parameter explanations and safe presets
- [x] Pre-compute configured all-pairs and known-payload workload report
- [x] Versioned workflow-stage and committed optimizer-decision reporting
- [x] Fresh-process objective/gradient wall-time and sampled-RSS protocol
- [ ] Prospective multi-size end-to-end runtime and peak-memory calibration
- [ ] Cross-platform CPU distribution
  - [x] Fresh GitHub-hosted Windows one-directory engineering freeze, complete
    frozen-process smoke contract, and independently inspected evidence artifact
  - [x] Hash-bound, noninterpreting installed-distribution metadata and
    license-file evidence contract for later human review
  - [x] Deterministic CycloneDX 1.7 post-build SBOM contract with explicit
    incomplete-composition and nonapproval boundaries
  - [ ] Reviewed release lock, SBOM, license clearance, signed installer, and
    clean-VM installation/uninstallation evidence
  - [ ] Separately gated Linux and macOS CPU distributions
- [ ] Validated NVIDIA GPU distribution
- [ ] Apptainer workflow for HPC environments

## Milestone 4: Scientific release

- [ ] Frozen validation protocol and tolerances
- [ ] Multi-platform benchmark study
- [ ] External usability evaluation
- [ ] Complete user and methods documentation
- [ ] Archived release and DOI
- [ ] Software and/or methods-paper submission
