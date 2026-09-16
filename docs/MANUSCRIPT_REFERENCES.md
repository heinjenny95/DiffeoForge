# Annotated literature for the DiffeoForge manuscript

Search checked 2026-09-16. This is a broad, targeted narrative literature search,
not a systematic review or a claim of exhaustive coverage. Queries combined
Deformetrica/LDDMM, landmark-free morphometrics, shape modelling software,
alignment/scaling, kernel PCA, reproducibility and the three original datasets.
Publisher pages, original articles, author-hosted papers and official repositories
were used to verify titles, dates and identifiers. Citation chaining expanded the
search. Reviews and software/data resources are labelled separately.

Thirty-one scholarly sources follow. Selection prioritizes direct method credit,
closest prior workflows, challenges to broad claims, and case-study provenance.
The suggested uses are editorial recommendations, not findings of DiffeoForge.
An abstract/metadata check supports only the limited annotation provided; it is
not a claim to have critically reviewed every full paper or supplement. References
are a selection pool, not a requirement to cite all 31 in the final manuscript.

## Read first

- **R01, R03:** Credit the engine and the deformation representation.
- **R07, R08, R09:** Establish existing workflows and an honest software comparison.
- **R16, R17:** Address alignment/scaling and landmark-free versus landmark results.
- **R13, R25, R26:** Cite the original studies behind the three applications.
- **R21:** Credit kernel PCA while keeping it distinct from the LDDMM metric.

## A. Deformetrica, registration and shape geometry

### R01 — Bône et al. (2018) · core

Bône A, Louis M, Martin B, Durrleman S. **Deformetrica 4: An Open-Source Software
for Statistical Shape Analysis.** ShapeMI 2018, LNCS 11167:3–13.
[DOI: 10.1007/978-3-030-04747-4_1](https://doi.org/10.1007/978-3-030-04747-4_1).

- **Use:** Introduction/Methods; registration-engine attribution. Conference
  chapter; publisher abstract and metadata checked. Do not attribute its core
  algorithms to DiffeoForge or infer our exact backend version from the citation.

### R02 — Beg et al. (2005) · foundation

Beg MF, Miller MI, Trouvé A, Younes L. **Computing Large Deformation Metric
Mappings via Geodesic Flows of Diffeomorphisms.** International Journal of
Computer Vision 61:139–157.
[DOI: 10.1023/B:VISI.0000043755.93987.aa](https://doi.org/10.1023/B:VISI.0000043755.93987.aa).

- **Use:** Methods; LDDMM background. Author-institution abstract/metadata checked.
  Foundational image-registration theory, not a guarantee of anatomical
  correspondence or defect-free discretized mesh output.

### R03 — Durrleman et al. (2014) · core

Durrleman S et al. **Morphometry of anatomical shape complexes with dense
deformations and sparse parameters.** NeuroImage 101:35–49.
[DOI: 10.1016/j.neuroimage.2014.06.043](https://doi.org/10.1016/j.neuroimage.2014.06.043).

- **Use:** Methods; control points, momenta and atlas-based deformation
  representations. Original full-text method sections checked. Establishes the
  modelling framework, not DiffeoForge-specific pilot/QC validity.

### R04 — Vaillant & Glaunès (2005) · attachment method

Vaillant M, Glaunès J. **Surface Matching via Currents.** IPMI 2005, LNCS
3565:381–392.
[DOI: 10.1007/11505730_32](https://doi.org/10.1007/11505730_32).

- **Use:** Methods when the recorded attachment is Current. Conference paper;
  publisher abstract/metadata checked. Do not describe currents as identical to
  orientation-insensitive varifolds.

### R05 — Charon & Trouvé (2013) · attachment alternative

Charon N, Trouvé A. **The Varifold Representation of Nonoriented Shapes for
Diffeomorphic Registration.** SIAM Journal on Imaging Sciences 6:2547–2580.
[DOI: 10.1137/130918885](https://doi.org/10.1137/130918885).

- **Use:** Methods/background for nonoriented surface representations. Publisher
  abstract/metadata checked. Cite as an alternative unless a documented run
  actually uses Varifold attachment; do not retroactively relabel Current runs.

### R06 — Fletcher et al. (2004) · geometric statistics

Fletcher PT, Lu C, Pizer SM, Joshi S. **Principal Geodesic Analysis for the Study
of Nonlinear Statistics of Shape.** IEEE Transactions on Medical Imaging
23:995–1005.
[DOI: 10.1109/TMI.2004.831793](https://doi.org/10.1109/TMI.2004.831793).

- **Use:** Methods/discussion of tangent-space versus manifold statistics.
  Original author-hosted paper consulted. Background citation, not evidence that
  DiffeoForge computes exact principal geodesics.

## B. Closest workflows and complementary software

### R07 — Toussaint et al. (2021) · essential prior workflow

Toussaint N et al. **A landmark-free morphometrics pipeline for high-resolution
phenotyping: application to a mouse model of Down syndrome.** Development
148:dev188631.
[DOI: 10.1242/dev.188631](https://doi.org/10.1242/dev.188631).

- **Use:** Introduction/Discussion; close precedent for a Deformetrica-based
  biological pipeline. Original article and author repository consulted. Compare
  workflow scope, not an unsupported claim that surface analysis is new.

### R08 — Goparaju et al. (2022) · comparative benchmark

Goparaju A et al. **Benchmarking off-the-shelf statistical shape modeling tools
in clinical applications.** Medical Image Analysis 76:102271.
[DOI: 10.1016/j.media.2021.102271](https://doi.org/10.1016/j.media.2021.102271).

- **Use:** Introduction/Discussion; published comparison of ShapeWorks,
  Deformetrica and SPHARM-PDM. Publisher abstract/metadata checked. Its findings
  do not constitute a head-to-head DiffeoForge benchmark or clinical validation.

### R09 — Rolfe et al. (2021) · interactive morphometrics

Rolfe S et al. **SlicerMorph: An open and extensible platform to retrieve,
visualize and analyse 3D morphology.** Methods in Ecology and Evolution
12:1816–1825.
[DOI: 10.1111/2041-210X.13669](https://doi.org/10.1111/2041-210X.13669).

- **Use:** Introduction; established interactive morphological tools and format
  interoperability. Publisher record and official project citation checked.
  Avoid implying existing morphometrics tools are all command-line-only.

### R10 — Cates, Elhabian & Whitaker (2017) · correspondence software

Cates J, Elhabian S, Whitaker R. **ShapeWorks: Particle-Based Shape Correspondence
and Visualization Software.** In Statistical Shape and Deformation Analysis,
chapter 10:257–298.
[DOI: 10.1016/B978-0-12-810493-4.00012-2](https://doi.org/10.1016/B978-0-12-810493-4.00012-2).

- **Use:** Introduction/Discussion; a different established correspondence
  approach and visualization ecosystem. Publisher chapter and author-hosted
  source consulted. Not a description of DiffeoForge's internal algorithm.

### R11 — Adams & Otárola-Castillo (2013) · landmark-analysis ecosystem

Adams DC, Otárola-Castillo E. **geomorph: an R package for the collection and
analysis of geometric morphometric shape data.** Methods in Ecology and
Evolution 4:393–399.
[DOI: 10.1111/2041-210X.12035](https://doi.org/10.1111/2041-210X.12035).

- **Use:** Introduction/landmark-baseline context. Original publisher/author
  records checked. Cite as a dependency only if it was actually used in the
  reported analysis; background relevance alone does not imply use.

### R12 — Porto, Rolfe & Maga (2021) · automated landmark alternative

Porto A, Rolfe SM, Maga AM. **ALPACA: A fast and accurate computer vision approach
for automated landmarking of three-dimensional biological structures.** Methods
in Ecology and Evolution 12:2129–2144.
[DOI: 10.1111/2041-210X.13689](https://doi.org/10.1111/2041-210X.13689).

- **Use:** Introduction; automated landmark transfer is another way to reduce
  manual work. Original article/official project citation checked. It produces
  landmark representations, not the same output as a surface-deformation atlas.

### R13 — Zhang et al. (2022) · mouse-study provenance

Zhang C, Porto A, Rolfe S, Kocatulum A, Maga AM. **Automated landmarking via
multiple templates.** PLOS ONE 17:e0278035.
[DOI: 10.1371/journal.pone.0278035](https://doi.org/10.1371/journal.pone.0278035).

- **Use:** Mouse Methods/Results/Discussion; MALPACA and its manual-landmark
  reference. Original article checked. Its automated-versus-manual comparison
  is not identical to our deformation-versus-landmark comparison; reconcile
  cohort membership before direct quantitative claims.

## C. Morphometric interpretation and sensitivity

### R14 — Bardua et al. (2019) · dense landmarks

Bardua C, Felice RN, Watanabe A, Fabre A-C, Goswami A. **A Practical Guide to
Sliding and Surface Semilandmarks in Morphometric Analyses.** Integrative
Organismal Biology 1:obz016.
[DOI: 10.1093/iob/obz016](https://doi.org/10.1093/iob/obz016).

- **Use:** Introduction/Discussion; practical semilandmark methods and anatomical
  sampling choices. Original article/institutional record consulted. Do not
  reduce landmark morphometrics to a few isolated points as a straw-man contrast.

### R15 — Mitteroecker & Schaefer (2022) · conceptual review

Mitteroecker P, Schaefer K. **Thirty years of geometric morphometrics:
Achievements, challenges, and the ongoing quest for biological meaningfulness.**
American Journal of Biological Anthropology 178(S74):181–210.
[DOI: 10.1002/ajpa.24531](https://doi.org/10.1002/ajpa.24531).

- **Use:** Introduction/Discussion; biological meaning and methodological scope.
  Review; publisher abstract/sections checked. Supports conceptual framing, not
  experimental evidence that one representation is superior in our datasets.

### R16 — Roberts, Camaiti & Goswami (2026) · essential recent study

Roberts LE, Camaiti M, Goswami A. **The impact of alignment and scaling on
biological inferences from landmark-free morphometrics.** Journal of Anatomy,
early online publication, first published 16 August 2026.
[DOI: 10.1111/joa.70227](https://doi.org/10.1111/joa.70227).

- **Use:** Introduction/Discussion; explicitly motivates reporting alignment and
  scaling. Original full text checked. Findings in its studied shapes do not
  prove that scaling explains our particular discrepancies. Refresh final issue
  metadata before submission; do not invent an assigned volume/page range.

### R17 — Mulqueeney, Ezard & Goswami (2025) · essential comparison

Mulqueeney JM, Ezard THG, Goswami A. **Assessing the application of landmark-free
morphometrics to macroevolutionary analyses.** BMC Ecology and Evolution 25:38.
[DOI: 10.1186/s12862-025-02377-9](https://doi.org/10.1186/s12862-025-02377-9).

- **Use:** Discussion; landmark-free versus dense-landmark analyses, preparation
  effects and downstream inference. Original full text checked. A close match to
  our methodological questions, not a blanket recommendation to close all meshes
  or a guarantee that all biological conclusions agree.

### R18 — Klingenberg (2016) · allometry review

Klingenberg CP. **Size, shape, and form: concepts of allometry in geometric
morphometrics.** Development Genes and Evolution 226:113–137.
[DOI: 10.1007/s00427-016-0539-2](https://doi.org/10.1007/s00427-016-0539-2).

- **Use:** Methods/Discussion; distinguish size normalization from allometric
  shape correction. Original review consulted. Relevant to both alignment modes
  and interpretation; do not label shape-only results as automatically allometry-free.

## D. Alignment and shape-space comparison methods

### R19 — Gower (1975) · alignment

Gower JC. **Generalized Procrustes Analysis.** Psychometrika 40:33–51.
[DOI: 10.1007/BF02291478](https://doi.org/10.1007/BF02291478).

- **Use:** Methods; GPA foundation. Publisher abstract/metadata checked. Report
  our actual scaling/reflection options separately. Use original publication
  year 1975, not the publisher's later online-platform migration date.

### R20 — Gower (1966) · distance ordination

Gower JC. **Some distance properties of latent root and vector methods used in
multivariate analysis.** Biometrika 53:325–338.
[DOI: 10.1093/biomet/53.3-4.325](https://doi.org/10.1093/biomet/53.3-4.325).

- **Use:** Methods; principal-coordinate/classical distance embedding background.
  Publisher abstract/metadata checked. Document the actual distance matrix and
  negative-eigenvalue handling; PCoA is not a distinct biological validation.

### R21 — Schölkopf, Smola & Müller (1998) · kernel PCA

Schölkopf B, Smola AJ, Müller K-R. **Nonlinear Component Analysis as a Kernel
Eigenvalue Problem.** Neural Computation 10:1299–1319.
[DOI: 10.1162/089976698300017467](https://doi.org/10.1162/089976698300017467).

- **Use:** Methods; KernelPCA foundation. Publisher/institutional records checked.
  State kernel and centering explicitly; this citation does not justify any
  particular RBF bandwidth or equate RBF KernelPCA with the LDDMM metric.

### R22 — Tenenbaum, de Silva & Langford (2000) · Isomap

Tenenbaum JB, de Silva V, Langford JC. **A global geometric framework for
nonlinear dimensionality reduction.** Science 290:2319–2323.
[DOI: 10.1126/science.290.5500.2319](https://doi.org/10.1126/science.290.5500.2319).

- **Use:** Methods; Isomap credit. Original abstract/metadata checked. Report
  neighborhood construction and disconnected-graph handling; a nonlinear plot
  does not by itself establish a biological continuum.

### R23 — Coifman & Lafon (2006) · diffusion maps

Coifman RR, Lafon S. **Diffusion maps.** Applied and Computational Harmonic
Analysis 21:5–30.
[DOI: 10.1016/j.acha.2006.04.006](https://doi.org/10.1016/j.acha.2006.04.006).

- **Use:** Methods; diffusion-based embedding credit. Publisher abstract/metadata
  checked. Specify kernel, normalization and diffusion-time settings; resulting
  eigenvalues are not interchangeable with Cartesian PCA variance fractions.

### R24 — Jolliffe & Cadima (2016) · PCA review

Jolliffe IT, Cadima J. **Principal component analysis: a review and recent
developments.** Philosophical Transactions of the Royal Society A
374:20150202.
[DOI: 10.1098/rsta.2015.0202](https://doi.org/10.1098/rsta.2015.0202).

- **Use:** Methods/Discussion; PCA concepts, variance and representation.
  Original review consulted. Helpful for clear terminology; not a validation
  source for our numerical implementation.

## E. Biological case-study references and related application

### R25 — Casadei-Ferreira et al. (2021) · ant-study provenance

Casadei-Ferreira A et al. **Head and mandible shapes are highly integrated yet
represent two distinct modules within and among worker subcastes of the ant
genus Pheidole.** Ecology and Evolution 11:6104–6118.
[DOI: 10.1002/ece3.7422](https://doi.org/10.1002/ece3.7422).

- **Use:** Ant Methods/Results; original biological questions, landmark design
  and data provenance. Original article checked. Agreement with a reconstructed
  mandible morphospace does not replicate the complete head–mandible integration
  analysis. Dataset record D01 should be cited separately.

### R26 — Chalazoniti, Lattanzi & Halazonetis (2024) · human-study provenance

Chalazoniti A, Lattanzi W, Halazonetis DJ. **Shape variation and sex differences
of the adult human mandible evaluated by geometric morphometrics.** Scientific
Reports 14:8546.
[DOI: 10.1038/s41598-024-57617-7](https://doi.org/10.1038/s41598-024-57617-7).

- **Use:** Human Methods/Discussion; source cohort and landmark/semilandmark
  approach. Original publisher full text checked. Full-surface content differs
  from selected landmarks; neither this reference nor our visual screen proves
  that teeth cause our morphospace variation. Dataset record D03 is separate.

### R27 — Imirzian et al. (2024) · related ant LDDMM application

Imirzian N, Püffel F, Roces F, Labonte D. **Large deformation diffeomorphic mapping
of 3D shape variation reveals two distinct mandible and head capsule morphs in
Atta vollenweideri leaf-cutter worker ants.** Ecology and Evolution 14:e11236.
[DOI: 10.1002/ece3.11236](https://doi.org/10.1002/ece3.11236).

- **Use:** Introduction/Discussion; directly relevant prior biological use of
  Deformetrica and momenta analysis. Original methods/results sections checked.
  This is Atta, not the Pheidole dataset used for our completed ant case study.

## F. Reproducibility and computational implementation

### R28 — Wilson et al. (2017) · computing practice

Wilson G, Bryan J, Cranston K, Kitzes J, Nederbragt L, Teal TK. **Good enough
practices in scientific computing.** PLOS Computational Biology 13:e1005510.
[DOI: 10.1371/journal.pcbi.1005510](https://doi.org/10.1371/journal.pcbi.1005510).

- **Use:** Introduction/Methods; motivation for organized, recorded workflows.
  Original guidance article checked. Cite principles, not evidence that our GUI
  measurably reduces errors or training time without a usability study.

### R29 — Sandve et al. (2013) · computational provenance

Sandve GK, Nekrutenko A, Taylor J, Hovig E. **Ten Simple Rules for Reproducible
Computational Research.** PLOS Computational Biology 9:e1003285.
[DOI: 10.1371/journal.pcbi.1003285](https://doi.org/10.1371/journal.pcbi.1003285).

- **Use:** Methods/Availability; track inputs, code versions, parameters and
  intermediate decisions. Original guidance article checked. A saved report
  alone is not a demonstration that an independent rerun is reproducible.

### R30 — Wilkinson et al. (2016) · FAIR principles

Wilkinson MD et al. **The FAIR Guiding Principles for scientific data management
and stewardship.** Scientific Data 3:160018.
[DOI: 10.1038/sdata.2016.18](https://doi.org/10.1038/sdata.2016.18).

- **Use:** Availability/Discussion; reusable metadata and research objects.
  Original principles/comment article checked. Do not claim FAIR certification
  or treat FAIR as permission to publish private or restricted datasets.

### R31 — Charlier et al. (2021) · conditional backend credit

Charlier B, Feydy J, Glaunès JA, Collin F-D, Durif G. **Kernel Operations on the
GPU, with Autodiff, without Memory Overflows.** Journal of Machine Learning
Research 22(74):1–6.
[Official article](https://jmlr.org/papers/v22/20-275.html).

- **Use:** Methods when KeOps was actually used; kernel-reduction engineering.
  Official journal metadata/abstract checked. Does not imply unlimited memory,
  universal GPU compatibility or guaranteed performance of our whole workflow.

## G. Data records and software resources — not additional research papers

- **D01 — Pheidole source data:**
  [Dryad record, 10.5061/dryad.1rn8pk0sz](https://doi.org/10.5061/dryad.1rn8pk0sz).
  Linked by R25. Cite the record as well as the paper; verify redistribution terms
  for the final evidence package. The DOI resolver was intermittently unavailable
  during this search, so the paper's data statement also anchors this reference.
- **D02 — Mouse source repository:**
  [SlicerMorph/Mouse_Models](https://github.com/SlicerMorph/Mouse_Models).
  Official repository inspected; use a pinned revision and specimen manifest in
  Methods, not a moving default branch as the only provenance record.
- **D03 — Human source data:**
  [Maxillofacial bone dataset for the MARGO project, v0.5.0](https://zenodo.org/records/10170185),
  DOI 10.5281/zenodo.10170185. Record inspected; keep data-version citation separate
  from R26 and verify the applicable license for redistributed derived files.
- **S01 — Existing Deformetrica GUI prior art:**
  [ClinicalCardiovascEngGroup/SSM](https://github.com/ClinicalCardiovascEngGroup/SSM).
  Author-maintained software repository inspected; includes a MATLAB interface
  around Deformetrica. It rules out an unqualified first-GUI claim; do not infer
  current maintenance, platform support or equivalence to DiffeoForge.
- **S02 — Prior biological workflow implementation:**
  [Toussaint's landmark-free-morphometry repository](https://gitlab.com/ntoussaint/landmark-free-morphometry).
  Original software accompanying R07; useful for a feature-by-feature scope
  comparison. Record an inspected version before asserting implementation parity.

## What this search changes in the manuscript

- Emphasize guided decisions, auditability and same-atlas representation comparison,
  not first software, first GUI, first biological application or a new engine.
- Discuss landmark disagreement as a scientifically meaningful comparison, while
  preserving alternative explanations and incomplete quality evidence.
- Explain parameter dependence and analysis choices concretely; avoid calling
  every choice arbitrary or suggesting that a pilot proves universal optimality.
- Read co-author-selected core papers in full before final claim/citation approval;
  refresh recent bibliographic metadata and source/software versions at submission.
