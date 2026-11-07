# Pilot robustness: source audit and qualification plan

Status: first engineering implementation in v122, 13 October 2026. Screening
detail checks and stop-aware continuation are covered in
[v122 scope](V122_PILOT_DETAIL_AND_CONTINUATION.md); broader qualification and the
remaining proposals below stay open. No running job or saved scientific result
is changed by this document. The goal is fewer failed
or repeated pilot trials while retaining fit quality across mesh families and
deformation magnitudes. Universal success on arbitrary meshes is not established.

## Verified current behavior

- Pilot selection already uses normalized, area-based surface descriptors, a
  medoid and farthest-first coverage, with optional required/declared subjects.
  It is a diversity heuristic, not proof of unseen-specimen coverage. The default
  requested count is eight (`reference_calibration.py`).
- Fit search already uses simplified scientific screening targets, full-target
  confirmation, individual recovery, progressive refinement and joint fitting.
  The template retains its full topology. Working targets default to 20,000
  triangles; the initial control-grid target defaults to 200
  (`reference_fit_search.py`). v122 adds measured discrete detail checks,
  bounded resolution escalation and original fallback; the initial constants
  themselves do not certify approximation fidelity.
- The fit-search route measures original surfaces with 2,048 area-stratified
  point-to-triangle samples per direction, recording p95, p99 and mean. Older
  generic metrics can use sampled nearest vertices. Metric identity and scope
  must remain explicit; neither proxy establishes anatomical correspondence.
- Adaptive search defaults to twelve additional runs, three rounds and 300
  iterations per trial. It rejects measured per-specimen regressions when moving
  the center and stops below a 1% progress heuristic. These are computational
  search limits, not universal fit thresholds (`adaptive_calibration.py`).
- Changing deformation kernel or control basis starts a new field. Compatible
  warm starts are reused. The audit found tenfold automatic tolerance tightening
  even for cap-limited observations. v122 retains exact seed tolerance and skips
  unchanged-model continuation after explicit tolerance stops. No precision or
  final quality criterion is changed.
- Anatomical decisions, fixed-state integration and optimizer convergence remain
  separate. A provisional capped result is not a converged recommendation.

## Prioritized improvements

### 1. Measure screening fidelity and preserve local features

Replace fixed triangle-count suitability assumptions with a declared geometric
error budget, connected-component coverage and detail checks against originals.
Report approximation error relative to the requested matching/feature scale.
Escalate screening resolution when that error is too large, or retain the original
when a safe approximation cannot be established. Do not invent a universal
triangle-count or kernel/edge ratio that guarantees anatomical fidelity.

Add independent sample sets and regional diagnostics for protrusions, thin parts
and high residual patches. Global p95 can miss a small but important structure;
p99 alone still cannot prove local anatomy. Any detected region should be bound
to source geometry and identified consistently across candidate comparisons.
Full-target confirmation and human review remain mandatory. Screening never
approves a final fit or replaces the final scientific geometry.

### 2. Diagnose the reason for another trial

Distinguish numerical work remaining, insufficient deformation capacity, missing
matching detail, alignment/template sensitivity and actual specimen trade-offs.
Use native stopping reasons, full-precision objective changes and residual maps.
An iteration-capped candidate can receive additional work under its retained
tolerance; it does not automatically need a stricter stopping criterion. A
tolerance-stopped continuation must declare a supported arithmetic/stopping
contract before requesting a tighter diagnostic threshold. Neither path may
manufacture convergence or weaken the final acceptance criterion.

Before proposing another trial for a persistent local-feature failure, audit the
saved result without fitting again:

- Bind the exact specimen, preferred/current attempts, native endpoint and viewer
  sources to their manifests and hashes. Compare full-resolution template, target
  and reconstruction; check the actual scientific working target separately from
  display proxies. A visible extra feature may already be present in the template.
- Trace effective XML settings and compatible warm-start fields across attempts.
  A denser control grid does not by itself change the deformation kernel width;
  rejection and relative preference are not a semantic feature-count objective.
  Keep a fixed reference template distinct from the deformation applied to it.
- Separate an iteration cap, explicit native tolerance and anatomical acceptance.
  Compare geometry directly when attachment settings differ; native objective
  values from different settings are not interchangeable fit-quality scores.
- Add bidirectional regional point-to-triangle distances on the original surfaces
  beside global summaries. Declare area weighting, coordinate units and any
  exploratory region/crop; a global percentile can conceal an important local
  mismatch. Component/orientation checks and anatomical feature counts answer
  different questions.

Report observed geometry and parameter/search restrictions separately from
untested explanations such as insufficient deformation scale, initialization,
attachment sensitivity or iteration budget. Any controlled fitting comparison
remains a separate, explicitly scoped next action; preserve saved evidence and
human review decisions. Do not silently turn anatomical notes into new loss terms.

For an explicitly requested template change, preserve the previous configuration,
alignment and pilot outputs. Keep the complete observation cohort: use a separate
template copy rather than silently dropping its source specimen or retaining the
old template copy as another observation. Copy the selected specimen's landmark
rows to the new template alias. If preparing a new GPA, publish separate,
hash-bound evidence and require fresh visual review; numerical convergence does
not transfer the old review approval. Do not carry old template-bound guidance,
pilot approvals or momentum fields into the new preparation. Retain absolute
numerical settings unless a parameter change was also requested, and label their
provenance accordingly. Verify the saved configuration, input identities,
alignment evidence and desktop convenience paths. An already-open desktop
session must reload the project before using the new preparation. Preparation
alone does not authorize or start a new fit.

Rank proposed experiments from the evidence instead of always exhausting the
same fixed-order list. Keep the current budget explicit and distinguish an
exhausted budget from a satisfactory fit. Preserve all prior candidates and
per-specimen protections. Speed is a secondary measure after quality eligibility.

### 3. Qualify coarse-to-fine state transfer

The current screening/progressive routes are useful foundations, but reducing a
target's triangles is different from optimizing deformation scales progressively.
Initially test compatible warm starts and controlled resolution schedules that
finish with the declared full scientific model. For a changed kernel/control
basis, explore a separate transport of the previous velocity field with recorded
reconstruction error; copying old momenta into the new basis is not equivalent.
On failed transfer qualification, retain the existing explicit fresh-field path.
Even successful transfer is initialization, not uninterrupted optimizer identity.

Wavelet-based multiscale LDDMM research motivates this direction, but its image
experiments do not validate a drop-in surface pilot or a speedup for this software:
[Gaudfernau et al., author-hosted preprint](https://lepennec.perso.math.cnrs.fr/Preprint/Health/2022-HAL-GBALP.pdf).

### 4. Qualify representation and cohort coverage

Provide an explicit Current/Varifold pilot comparison where appropriate, retaining
the same originals, alignment and evaluation. Currents can have orientation and
cancellation effects for sharp opposing surface elements; varifolds address
orientation dependence. This is a model comparison, not a universal superiority
claim or a silent change to an existing analysis:
[Charon and Trouve, 2013](https://arxiv.org/abs/1304.6108).

Report diversity coverage, then test held-out typical and extreme specimens.
Expand the pilot only when coverage or held-out reconstruction requires it; bind
the new cohort and repeat the affected joint evidence. Do not compare pooled
scores from different cohorts as though they were the same experiment. Preserve
required biological strata and explicit anatomical orientation. Investigate
template sensitivity with separately recorded alternatives.

## Acceptance before changing defaults

Use a prospectively declared comparison with the installed pilot as baseline.
Include smooth convex, thin, toothed/protruding, deeply concave and disconnected
surface families; vary mesh resolution and sampling irregularity independently
from mild, moderate and extreme known diffeomorphic shape differences. Test
orientation defects and invalid geometry as explicit rejection/diagnostic cases.
Topology-changing ground truth cannot be treated as an exactly attainable
diffeomorphic fit. Add deidentified/public real families before generalization.

Compare originals at the same final model and arithmetic settings using independent
area-based point-to-triangle measurements, per-specimen p95/p99, feature-region
errors, geometric validity and unchanged integration/convergence gates. Declare
measurement repeatability and any noninferiority margin before results are seen;
do not choose a margin to make a faster method pass. Human anatomical approval
is separate from metric ordering. A small feature cannot be traded away for a
better cohort mean.

Record evaluations, repeated trial count, wall time, peak memory and failure
reasons. Accept reduced work only after quality eligibility; retain a baseline
fallback when a proposed path regresses. Successful synthetic cases do not prove
all anatomies or arbitrary topologies. Keep failed experiments and run lineage.

The first implementation now covers discrete screening-fidelity/detail checks
and stop-reason-aware continuation; independent regional reconstruction metrics
remain a separate qualification task. Deformation-basis transport, representation
comparison and coverage expansion need separate native validation. No private
pilot rerun, existing-result conversion or server-runtime update is authorized
implicitly by this plan.
