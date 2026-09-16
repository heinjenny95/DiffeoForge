# Preprint readiness: priority checklist

Agreed planning scope: 2026-09-16. Status: **three existing workflow case studies;
remaining acceptance and manuscript-preparation tasks below**. This is not a
claim of universal scientific or release qualification.

DiffeoForge guides users through a reproducible Deformetrica workflow. It helps
them prepare inputs, choose defensible starting parameters, inspect registrations
and compare shape-space methods. It does **not** identify universally correct
parameters, approve biological interpretations or replace researcher judgement.

## Already demonstrated — reuse this evidence

- [x] Workflow application to **ant mandibles**, with an existing evaluation.
- [x] Workflow application to **mouse skulls**, with an existing atlas,
  landmark/shape-space comparison and Validation Lab evaluation.
- [x] Workflow application to **human mandibles**, with an existing large-mesh
  feasibility evaluation and documented limitations.

These are completed applications, not proposed future studies. The existing
project-document tabs **Ant Mandibles**, **mice skull** and **Human mandibles**
contain the evaluations and figures; the owner reaffirmed their status when
reviewing this checklist. The human-mandible record does not establish clinical
validation, cohort-wide anatomical sign-off or a causal dental explanation.

The remaining work is to consolidate this evidence for the manuscript and close
specific software/reproducibility gaps, not to demonstrate the workflow from
scratch. Reuse existing implementations, runs, figures and checks before adding
new work. Close remaining acceptance items with a candidate commit, linked
evidence and a named reviewer. No fourth dataset or repeat of all three studies
is required merely to fill this checklist.

## P0 — settle before freezing the preprint evidence

- [ ] **1. Make the advertised installation and complete Reference workflow reliable.**
  Diagnose the failed Windows installer lifecycle check; distinguish a packaging
  defect from an evidence-harness failure, fix the cause and rerun it. Reuse the
  three case studies for application evidence. Exercise remaining release-path
  and regression gaps on a bounded example:
  import → alignment → manual/AFK pilot → atlas → visual QC → comparison/export,
  including cancellation, interruption, reopening and continuation.
  **Done when:** a clean-machine test of the advertised route and relevant CI
  checks pass on the candidate; no lost work, duplicate jobs, silent failures or
  unintended launches. Document any unsupported route explicitly.

- [ ] **2. Audit scientific data handling and reproducibility.**
  Check units, coordinate systems, left/right handling, alignment/scaling,
  parameter values passed to Deformetrica, specimen identity and provenance.
  Scientific geometry must stay separate from display proxies. Record inputs,
  transforms, resolved parameters, backend/version, environment and outputs.
  **Done when:** a small public example can be rerun from the recorded bundle;
  matched direct-Deformetrica and guided execution agree within declared numerical
  tolerances. This establishes faithful orchestration, not biological validity.

- [ ] **3. Make pilot, AFK, QC and Validation Lab claims unambiguous.**
  Explain what the user's expected-variation choice changes, how candidates are
  ranked, and why recommendations are provisional. Provide a short AFK return
  summary with selected values, uncertainty/boundary warnings and the next human
  decision. Separate numerical diagnostics, visual plausibility and biological
  interpretation; no flagged cases does not guarantee a good fit. Keep Validation
  Lab optional and describe exactly what it varies (currently kernel/control-point
  settings, with noise fixed), rather than presenting a universal parameter test.
  **Done when:** UI, reports and Methods use consistent wording; automatic choices
  are traceable and never fabricate visual approval. Broader validation is needed
  only for broader claims, not as a compulsory step for every user.

- [ ] **4. Finish the essential usability/performance work.**
  Default NEW projects to Deformetrica Reference; preserve existing-project engine
  choices. Shorten the main screens and collapse detail without hiding decisions
  or important warnings. Add immediate busy feedback, real overall progress and
  explicit failures. Verify display proxies and synchronized mesh/landmark motion
  in every relevant viewer, especially QC, using representative large inputs.
  **Done when:** a recorded end-to-end acceptance test has no apparent dead buttons,
  misleading timers or unusable viewers; supported workload/resource limits are
  stated. Preserve original-detail inspection and scientific-resolution analysis.

- [ ] **5. Qualify and showcase the shape-space method comparison.**
  Audit feature definitions, specimen order, kernel centering/scaling/bandwidths,
  eigenvalue handling and every method's exported scores and agreement statistics.
  Verify comparisons tolerate PC sign/order changes and explain when subspace or
  distance agreement is more appropriate. Label PCA, kernel PCA, PCoA and other
  embeddings accurately; do not compare their variance percentages as if they
  were identical quantities or pick a biological "winner" automatically.
  **Done when:** small reference/regression cases agree with independent calculations;
  figures, tables, HTML and project-folder PDF agree and are reproducible from the
  same completed atlas. Include a concise comparison figure in the preprint.

## P1 — complete the evidence and author review before submission

- [ ] **6. Turn the three existing case studies into a compact manuscript package.**
  Select and harmonize the existing ant-mandible, mouse-skull and human-mandible
  figures, Methods summaries and limitations; do not commission new case studies.
  Reuse an existing public/synthetic example for the short end-to-end tutorial.
  Report cohort sizes, mesh face counts, hardware, elapsed time, memory/storage and
  relevant
  failures where measured; do not extrapolate unmeasured performance. Explain
  disagreements with landmark-based analyses as questions to investigate, not
  automatic failure or proof of superiority.
  **Done when:** the already completed applications are presented consistently,
  manuscript figures and numerical claims map to recorded runs, and
  public example data and redistribution permissions are checked. Unpublished
  colleague data remain private unless separately authorized.

- [ ] **7. Obtain independent technical and first-use review.**
  Ask a co-author/reviewer to inspect the parameter/PCA implementation and a new
  user to install and follow the tutorial without the developer guiding each step.
  Supply a versioned source snapshot and reproducible example, not private data.
  **Done when:** feedback and resolutions are recorded; correctness and workflow
  blockers are closed, and remaining limitations are stated. Review does not need
  to become another biological research project.

- [ ] **8. Freeze the manuscript scope and reproducibility record.**
  Align abstract, Methods, README, tutorial and limitations with the guided-workflow
  claim. Distinguish landmark-assisted alignment from landmark-free surface
  registration; cite/credit Deformetrica and the implemented analysis methods.
  Record the exact software version, dependency environment and data availability;
  review licenses, contribution statements and any archive/DOI plan with co-authors.
  **Done when:** every claim has evidence, all authors approve the draft, and the
  code/example associated with it are identifiable and accessible as described.
  Tagging, public binary releases, archiving and actual preprint submission require
  their own approval; this checklist does not authorize them.

## Not prerequisites for this scoped preprint

Replacing Deformetrica with the Modern engine; native installers for every OS;
universal GPU/HPC support; automatic biological interpretation; a proof of one
optimal parameter set; mandatory Validation Lab runs for all users; or new
large-scale biological studies. Keep these in the [roadmap](../ROADMAP.md).
Claim support only for demonstrated platforms and installation routes. A public
binary release still follows the separate [release checklist](RELEASE_CHECKLIST.md).

## Baseline and immediate next action

At planning baseline `c843e4cfaeee00c58bf6b84ee9c815a32cc148dd` (v81),
[CI](https://github.com/heinjenny95/DiffeoForge/actions/runs/34973901524) and the
[Reference container workflow](https://github.com/heinjenny95/DiffeoForge/actions/runs/34973901462)
passed, but the
[Windows installer lifecycle workflow](https://github.com/heinjenny95/DiffeoForge/actions/runs/34973901460)
failed at "Observe isolated current-user install smoke and uninstall".
The failure's cause remains undiagnosed. Existing offscreen/source CI is not
native distribution qualification for every OS.

**Next implementation task:** diagnose that installer/evidence failure, then
execute the bounded end-to-end acceptance test in item 1. Do not restart private
atlas studies, change their scientific settings or rebuild/install the app as
part of merely recording this plan.
