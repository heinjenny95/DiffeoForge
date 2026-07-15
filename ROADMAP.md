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
- [ ] Contribution issue templates and release checklist

## Milestone 1: Reproducible reference backend

- [x] Pinned CPU container for Deformetrica 4.3
- [x] Explicit XML generation from the public configuration
- [x] Immutable run directories and versioned manifests
- [x] VTK geometry preflight and mesh inventory
- [x] Local 8-subject CPU smoke test against the frozen environment
- [ ] Checkpoint, resume, and failure-state handling
- [x] Self-contained HTML input-validation report
- [ ] HTML convergence and result report
- [x] Reference results for the miniature dataset

## Milestone 2: Modern-engine feasibility

- [ ] Evaluate a focused Deformetrica dependency port
- [ ] Evaluate current PyTorch/KeOps-based libraries
- [ ] Prototype only the deterministic 3D surface-atlas path
- [ ] Compare gradients, objectives, deformations, and performance
- [ ] Record the engine decision in an ADR

## Milestone 3: Accessible application

- [ ] Local graphical interface backed by the shared core
- [ ] Parameter explanations and safe presets
- [ ] Resource estimation and progress reporting
- [ ] Cross-platform CPU distribution
- [ ] Validated NVIDIA GPU distribution
- [ ] Apptainer workflow for HPC environments

## Milestone 4: Scientific release

- [ ] Frozen validation protocol and tolerances
- [ ] Multi-platform benchmark study
- [ ] External usability evaluation
- [ ] Complete user and methods documentation
- [ ] Archived release and DOI
- [ ] Software and/or methods-paper submission
