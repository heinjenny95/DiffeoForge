# Public Reference observation — 2026-09-16

Scope: programmatic same-machine orchestration of the bundled CC0 synthetic
cohort, not a new empirical study or an independent first-user review. No private
meshes, checkpoints or researcher's running application were used or changed.

## What was exercised

- Import of six public VTK surfaces and four exact corresponding vertices per
  mesh, GPA preview/approval fingerprint, immutable aligned copies, surface-scale
  normalization and explicit unitless coordinates. The landmark table is now
  supplied in `examples/synthetic/landmarks.csv`.
- A real Deformetrica 4.3 Reference AFK pilot: 31 candidates across attachment,
  deformation, noise and timepoint stages, three pilot subjects, four CPU threads,
  and a 100-iteration candidate cap. Import/preparation plus pilot took 916.266 s
  on this local machine. This is an observation, not a general runtime promise.
- All four stages completed. Attachment/deformation/noise decisions were recorded
  as **ambiguous**, with unbounded search warnings; the timepoint decision was
  recorded as robust. Selected IDs: `attachment-06`, `deformation-05`, `noise-05`,
  `timepoints-01`. No visual approval was fabricated.
- A separate, explicitly initiated five-subject atlas converged at iteration 51
  with 36 control points. Starting it was a test-harness action, not an AFK effect.
- The same protected staged inputs, XML and execution environment were invoked
  directly through Deformetrica in an isolated output directory. Convergence,
  controls, momenta, residuals, estimated template and five reconstructions all
  matched: **10/10 numeric comparisons, zero observed difference, byte-identical
  files**, within predeclared maximum-absolute 1e-6 / RMS 1e-7 tolerances.
- Source-bound QC metrics covered all five subjects. Relative screening flagged
  `subject-04.vtk`; no human visual approval was recorded. The direct analysis
  export here tests backend APIs, not the GUI's human-review release gate.
- All nine comparison methods and a nine-page project PDF completed after the
  [method-dimension fix](SHAPE_SPACE_DIMENSION_HANDLING.md). The report was
  reverified and every PDF page was rendered and visually checked.

## Traceability and limits

Orchestration started with `16a3a1b2c27b6acb5544717958fcf4ea244d7e46`; the export
correction is `cc9b890c934d2ac30f2fb9a28f9aba18a7618954`. Run ID: `guided-public`.
The local run-manifest SHA-256 is
`31ec34206ca1eb1bb1733e9cc449d7291c1cabc23f12a7c12c4600cd751bd5c9`.
Local evidence is retained under the artifact workspace's
`artifacts/v83_workflow/public-workflow`, not committed as machine-specific output.

An initial observer stopped after the numerical comparisons because it accessed
an incorrect QC attribute. Its first direct-run log capture also lacked the
initial iteration; a second isolated direct invocation captured through a pipe
retained the complete log. Neither the guided atlas nor the pilot was repeated.
The full log and ten-file comparison, not the incomplete capture, support the
reported result. This observer repair is distinct from the real Isomap cache bug
found during export and fixed in the application.

Matching execution of the **same XML** checks orchestration fidelity; it does
not independently validate the XML derivation, mathematical model or anatomical
correspondence. Existing configuration/parameter and scientific regression tests
cover additional boundaries. A five-subject synthetic cohort does not establish
large-mesh performance, general parameter adequacy or biological validity.
Independent native installation/first-use review and scientific judgement remain
open; see [the preprint checklist](PREPRINT_READINESS.md).
