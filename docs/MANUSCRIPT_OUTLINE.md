# Manuscript outline

Planning draft, 2026-09-16. This is an outline, not a submitted manuscript or a
statement that the preprint acceptance checklist is complete. Private numerical
findings and figures remain in the project document; none are reproduced here.
Reference IDs below resolve in [Annotated literature](MANUSCRIPT_REFERENCES.md).

## Working title and central contribution

- **DiffeoForge: a guided, reproducible workflow for Deformetrica-based surface morphometrics.**
- Contribution: make preparation, parameter exploration, registration review,
  shape-space comparison and provenance accessible within one guided workflow.
- Deformetrica provides the registration engine. DiffeoForge does not introduce
  a new LDDMM theory, certify universally correct parameters or interpret biology.
- Reuse four existing applications: ant mandibles, mouse skulls, human mandibles
  and weevil trochanters. The trochanter comparison adds an earlier atlas/linear
  PCA baseline; reconcile historical runs rather than require a new atlas.

## Abstract — bullet draft

- **Background:** Surface-based morphometrics complements landmarks, but input
  preparation, parameter decisions and reproducibility remain substantial tasks.
- **Approach:** Introduce a guided Deformetrica workflow linking mesh checks,
  alignment, pilot exploration, atlas execution, visual QC and analysis exports.
- **Distinctive analysis feature:** Compare several shape-space representations
  from the same completed atlas without repeating registration.
- **Evidence:** Present four existing biological/medical-mesh applications,
  landmark comparisons where available, the historical trochanter workflow
  comparison, and practical limitations. Final figures remain subject to run/QC
  reconciliation.
- **Conclusion:** Support transparent, defensible researcher decisions; numerical
  success, stable embeddings and anatomical validity are different questions.
- Insert final verified headline results only after figure/run reconciliation;
  avoid universal accuracy, speed or clinical-validation claims.

## 1. Introduction

- Why quantify 3D morphology? Introduce landmarks and dense semilandmarks as
  established, biologically informed representations, not obsolete alternatives
  [R11, R14, R15].
- Introduce full-surface deformation representations and the Deformetrica/LDDMM
  foundations; distinguish surface registration from explicit point homology
  [R01–R05].
- Position against existing workflows: Toussaint's pipeline, SlicerMorph,
  ShapeWorks and clinical benchmarking. Do not claim the first GUI or first
  landmark-free pipeline [R07–R10; software resource S01].
- Explain the practical gap targeted here: connected guidance and recorded
  decisions from inputs through QC to alternative shape-space analyses.
- Motivation for transparency: alignment, scaling, representation and mesh
  preparation can affect inferences; parameter choice is study-dependent
  [R16–R18].
- State scope: a workflow/software contribution illustrated by four existing
  applications, not a new biological theory or automated optimal-parameter oracle.

## 2. Materials and methods

### 2.1 Software architecture and reproducibility

- Describe the GUI/orchestration layer, Deformetrica backend, project structure,
  recorded configurations and output provenance [R01, R28–R30].
- Report exact application/backend/dependency versions, numerical precision,
  seeds, hardware and demonstrated installation route; separate supported from
  experimental paths. Cite KeOps only for runs actually using it [R31].
- Separate implemented behavior, tested behavior and remaining acceptance work;
  an available button alone is not evidence of scientific qualification.

### 2.2 Inputs, mesh quality and alignment

- Report mesh/landmark import, specimen pairing, units, coordinate transforms,
  handedness and explicitly documented working-copy repairs.
- Explain structural blocking conditions versus study-dependent open-surface
  and component warnings; do not silently close, smooth or discard anatomy.
- Describe the selected alignment/scaling mode and landmark roles [R19].
  Landmark-assisted prealignment is not a fully landmark-free pipeline.
- Keep scientific meshes separate from reduced display proxies; report analysis
  face counts independently from visualization resolution.

### 2.3 Pilot calibration and atlas execution

- Define attachment representation/kernel, deformation kernel, control-point
  spacing, noise/fit weighting, time discretization and stopping criteria
  [R01–R05]. Report actual resolved values, not only slider labels.
- Explain what expected-variation preferences change, the explored ranges,
  ranking metrics, boundary/uncertainty flags and manual overrides.
- Describe AFK as automatic adoption of recommendations within a recorded search,
  not proof of optimal settings or substitute anatomical approval.
- Document initialization, pilot subset, final cohort and whether convergence
  criteria or iteration/time limits terminated each run.

### 2.4 QC and optional sensitivity analysis

- Separate numerical diagnostics, visual inspection and biological interpretation.
  Record flagged cases, review decisions and incomplete review explicitly.
- Describe Validation Lab's actual finalists, resampling, frozen-template holdout
  design and decision rule. State the tested parameter dimensions and fixed noise.
- Explain diagnostic approximations and sampling; neither low residual nor low
  distortion alone demonstrates anatomical correspondence.
- Distinguish a reserved holdout from data subsequently used for further tuning.

### 2.5 Shape-space and reference comparisons

- Define the default LDDMM deformation-kernel/metric-tangent PCA, Cartesian
  momenta PCA, tangent-distance PCoA, adaptive RBF KernelPCA variants,
  fixed-gamma compatibility preset, Isomap and diffusion maps [R06, R20–R24].
- Do not conflate an LDDMM kernel-induced metric with a generic RBF kernel on
  flattened momenta, or a tangent approximation with exact principal geodesics.
- Report centering, bandwidths, normalization, neighbor settings, eigenvalue
  treatment and specimen order. All same-atlas comparisons share registration.
- Use distances, neighborhoods and aligned subspaces alongside individual PCs;
  account for sign/order ambiguity. Variance fractions from different kernels or
  embeddings are not automatically comparable quantities.
- Specify reconstructed landmark baselines, common specimens, alignment and
  scaling. Pairwise distances are dependent observations; avoid naive tests
  treating all specimen pairs as independent replication.

### 2.6 Existing datasets and comparison design

- Ant mandibles: published Pheidole dataset and geometric morphometric reference
  [R25, D01]. Distinguish our surface analysis from the original integration study.
- Mouse skulls: MALPACA source dataset and manual landmarks [R13, D02]. Match
  inclusion lists before any claim of direct replication or method ranking.
- Human mandibles: MARGO data and the published landmark/semilandmark analysis
  [R26, D03]. Document paired-cohort selection, dental scope and QC coverage.
- Weevil trochanters: the screw-joint preprint [R32] and existing atlas analyses.
  Treat this as a historical surface-workflow comparison, not automatically a
  landmark baseline. Match specimens, mesh resolution/repairs, alignment/scaling,
  atlas parameters and PCA definitions before quantitative cross-run claims.

## 3. Results — reuse completed evidence

### 3.1 Guided workflow and traceable outputs

- Show input checks → alignment → pilot → atlas → QC → shape-space comparison.
- Use one compact screen/decision example and an exported provenance record.
  Report measured performance and failures without extrapolating to all hardware.

### 3.2 Ant mandibles

- Summarize the completed application and comparison with the reconstructed
  landmark baseline; distinguish overall variation from within-group agreement.
- Reuse existing paired-caste and atlas-comparison figures. State which run,
  scaling and PCA definition produced each figure; do not mix earlier variants.
- Include outstanding anatomical review and allometry caveats [R18, R25].

### 3.3 Mouse skulls

- Demonstrate the larger-mesh workflow and partial agreement/disagreement with
  the manual-landmark representation; retain negative or ambiguous findings.
- Present completed Validation Lab evidence as a limited fit–regularity trade-off,
  not proof that a new setting resolves the landmark discrepancy [R13, R16, R17].
- Clearly distinguish the original full-cohort atlas from validation finalists
  for which no replacement full-cohort morphospace was generated.

### 3.4 Human mandibles

- Present a bounded medical-mesh feasibility application with existing shape
  visualizations and measured computational workload [R26].
- Describe mixed bony and dental content; do not claim teeth cause the observed
  morphospace without a targeted test. A diffuse plot is not evidence of no signal.
- State incomplete QC and absence of clinical validation. Do not turn this
  demonstration into a new tooth-segmentation study merely to complete the paper.

### 3.5 Weevil trochanters

- Reuse the earlier atlas and owner-reported linear PCA as a historical baseline;
  confirm its exact feature definition and source bundle against the preprint
  before labelling it Cartesian momenta PCA or reproducing published figures.
- Keep historical paper-versus-DiffeoForge comparisons separate from comparing
  ordinations of one fixed atlas. Different preparation or atlas parameters make
  cross-run differences inseparable from a change in PCA alone.
- Reuse the existing later method-comparison bundle where appropriate. Distinguish
  Cartesian momenta PCA, LDDMM deformation-kernel metric-tangent PCA and generic
  nonlinear RBF KernelPCA; do not silently replace the historical analysis.
- Assess matched-specimen distances, neighborhoods and subspaces, not identical
  PC axes. Existing momenta/control points may support missing postprocessing
  after provenance checks; no atlas rerun is requested by this editorial addition.
- Do not claim replication of the preprint's functional/phylogenetic conclusions
  or independent external validation from a reused development dataset [R32].

### 3.6 Same-atlas shape-space comparison

- Showcase where methods preserve similar relationships and where neighborhoods
  or axes change. Explain any mathematical equivalences and scale effects.
- Do not select a biological winner automatically or count agreement among
  methods derived from the same atlas as independent external validation.

## 4. Discussion

- Main contribution: lower operational barriers and preserve explicit decisions;
  user expertise still defines anatomy, study scope and defensible parameters.
- Position the contribution relative to existing software/pipelines, rather than
  claim novelty for Deformetrica or full-surface analysis [R07–R10, R27, S01].
- Discuss why landmark and surface morphospaces may differ: anatomical weighting,
  scaling, allometry, cohort composition, locality and registration quality.
  Present these as hypotheses unless tested [R14–R18].
- Explain that size normalization does not itself remove allometric shape
  variation [R18]; sign alignment alone cannot explain every discrepancy.
- Emphasize the value of method comparisons as sensitivity evidence, not an
  algorithmic replacement for biological interpretation [R17, R20–R24].
- Use trochanters to distinguish workflow continuity from representation
  sensitivity. A change of PCA can alter the morphospace without demonstrating
  that the earlier biological study was wrong or the newer method is superior.
- Limitations: mesh/segmentation content, uncertain correspondence, parameter
  coverage, incomplete QC, diagnostic sampling and high computational cost.
- Delimit claims: no universal optimal settings, clinical readiness, guaranteed
  scalability, all-platform installers or demonstrated usability gains without
  the relevant evidence. Modern-engine replacement remains future work.

## 5. Conclusion

- DiffeoForge connects established methods in a guided and auditable workflow.
- Four existing applications illustrate utility and limitations; researchers
  retain responsibility for parameter justification and interpretation.

## Figures, tables and supplementary material — planned

- **Figure 1:** Workflow and human decision points, including optional Validation
  Lab and same-atlas comparison; distinguish automated steps from human approval.
- **Figure 2:** Compact pilot/QC interface example with the recorded decision trail.
- **Figure 3:** Four existing case-study panels with matched labels and explicit
  reference definitions; reuse current project-document figures where suitable.
- **Figure 4:** Shape-space agreement/comparison, showing both stability and
  disagreement rather than only favorable examples. A trochanter panel can
  contrast historical linear PCA and current representations, explicitly marking
  whether they share one atlas or come from different runs.
- **Table 1:** Cohort/source, analysis faces, landmark role, alignment, exact
  parameters, backend/hardware, measured time/resources and QC status per case.
- **Supplement:** Versioned configurations, transforms, inclusion lists,
  diagnostic definitions, analysis settings and a licensed public/synthetic
  reproducible tutorial. Publish only authorized data and results.

## Availability, authorship and next editorial steps

- Credit Deformetrica, methods, data creators and dependencies separately.
  Record code/license/version, data access conditions, contributions, funding,
  conflicts and applicable reused-human-data ethics statements.
- First agree on the contribution/title and the four figure slots with co-authors;
  then reconcile existing figures/numbers with their source runs and QC status.
- Complete [preprint acceptance items](PREPRINT_READINESS.md), independent review
  and author approval before freezing the evidence. Archiving, public releases
  and submission require separate authorization.
