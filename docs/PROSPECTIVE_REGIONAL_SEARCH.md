# Regional automatic-search development and qualification

This work tests newly optimized fields selected from saved marked-area feedback.
Replaying a known successful field does not qualify this search. The installed
desktop runtime remains unchanged while this experimental policy is evaluated.

## Search and preservation

- The first protected trial optimizes the saved broad field itself on the same
  controls and movement kernel. Check the other attachment model on that broad
  basis before freezing it for independent residual corrections. A fixed earlier
  field is not equivalent to newly optimizing that field.
  Both attachment models use the same original saved initializer and protection
  frame; the second model must not inherit the first model's newly optimized
  field. Human comparison preference remains independent of this common start.
- Measure the retained fit's marked-surface mismatch before narrowing the
  attachment scale. A missing target surface outside the current capture range
  first receives a broader capture hypothesis.
- New residual controls cover both the retained source and original target,
  rather than only the short or misplaced source. Occupied surface voxels and a
  coarse bounding grid have an explicit support-distance and resource receipt.
  Full-surface corrections declare a bounded spacing policy: start at half the
  unchanged movement width and, only if the control limit is exceeded, increase
  spacing by 1.125 up to that width. Retain every occupied voxel; never truncate
  points to meet the cap. The staged receipt records each attempted count and
  the actual support bound `sqrt(3) * spacing / 2`. If even the broadest declared
  spacing exceeds the limit, preparation fails without native dispatch. Local
  marked-halo grids retain their existing fixed-spacing policy. This changes a
  newly zero-initialized residual basis, never an existing field's coefficients
  or movement kernel. Surface weights and physical preservation limits stay fixed.
- Keep useful coarse fields as an immutable prefix. A finer movement basis starts
  with zero residual momenta; existing coefficients are never reinterpreted under
  a different deformation kernel. A compatible warm continuation retains its
  own controls, momenta and prefix.
  A finer basis keeps the previous local surface weight, with an explicit noise
  floor for older overly strong terms. It must not simultaneously introduce a
  hundreds-fold local weight increase. Weight continuation is recorded separately
  from the movement-scale hypothesis.
- Soft position anchors regularize unmarked locations already close to the original.
  Incorrect unmarked positions are not automatically frozen. Explicit fixed marks
  retain their stricter position check. Automatic preservation checks the original
  surface geometry, allowing tangential remapping of an unchanged surface rather
  than treating its vertex parameterization as anatomical correspondence.
  Independently check previously good target
  surfaces, transitions, whole-surface geometry and new intersection flags.
- After unsuccessful local hypotheses, a declared global method/scale/weight
  contrast can test the other attachment model. This is a grouped hypothesis,
  not an isolated causal comparison of Current and Varifold.
- A useful local result with substantially larger whole-surface error receives a
  same-field weight-balancing hypothesis before further narrowing its movement
  basis. A far spatial-bin whole-surface tail instead broadens global capture,
  with proportional global-noise rescaling and unchanged local settings. This is
  a declared heuristic contrast, not an exact kernel normalization theorem.
  Later finer local controls cover the marked halo; a full-surface fine grid is
  reserved for a global method contrast so local detail does not automatically
  exceed the control resource bound. Human preference and anatomical approval remain separate from numerical
  initialization and controlled test-reviewer feedback.

These formulas are heuristics under qualification, not a diagnosis from a marked
region. Every new trial still requires a separate Run action in the desktop UI.
No tooth counts, species-specific rules or private reference fields enter the
production policy. A comparison mesh may be used by an independent test judge;
its metrics must not be supplied as proposal inputs.

## Consistent numerical frames

Residual fitting and evaluation use the same qualified retained ambient field.
Regional native trials use RK2 with at least 19 timepoints and a convergence
tolerance no looser than 1e-6. Saved fields are evaluated on the full original
source in Float64 with adaptive temporal and conforming spatial checks. This
changes the regional numerical protocol explicitly; it does not claim bitwise
identity with earlier Euler trajectories.

Conforming refinement retains a hash-bound original source grid. Triangle-area
QC compares matching connectivity on that grid, rather than comparing a refined
reconstruction with an older unrefined template. Unexpected connectivity changes
and changed source hashes remain errors.

New contact flags also trigger conforming original-source refinement outside the
marked halo. Their material points are evaluated through the same unchanged
fields, retaining all existing endpoint coordinates. The verified original coarse
template determines whether contacts are pre-existing input defects. If it is
clean, even contacts inherited from a discretized prefix trigger refinement;
they must not be exempted merely because they appear in that prefix too. If the
coarse input has contacts, the incoming-prefix exemption remains. Refinement
permits at most 16 passes for a clean input and eight otherwise, with the same
500,000-vertex cap and unchanged final acceptance checks. The original material
grid remains the subdivision domain; this neither sculpts an endpoint nor
repairs an invalid original input.

## Preparation cost and evidence

An operation-scoped manifest cache verifies each immutable ancestor once within
one action. Manifest hashes and transitive file identities are checked again on
reuse. Nothing survives into a later action or Run. Fresh child assets may be
staged inside the scope; verified parents are immutable and child sealing/journal
writes occur after the scope exits.

Native optimizer time, preparation and dense postprocessing are different costs.
The short optimizer duration alone must not be described as total waiting time.
Private qualification evidence preserves unsuccessful trials, actual staged
inputs, native files, source hashes and independent final-geometry comparisons.

## Remaining acceptance gates

An experimental recovery stage addresses the remaining surface once both marked
distance tails reach the retained preservation tolerance and numerical guards
pass. It retains all previous fields and the local objective, adds full-surface
source/target control support, and derives a global capture scale from measured
whole-surface errors. Automatic soft anchors can be relaxed only with unused
preservation slack and no explicitly fixed areas. Geometric preservation limits
remain unchanged. This grouped hypothesis needs a new optimized result and full
rechecking; proposing it is not evidence that it improves the fit.

A Same/Worse global trial that fails the measured comparison is excluded from
the next numerical prefix. The search verifies the retained good reference and
tests finer global attachment/movement resolution from it, holding local settings.
If that trial already reduced whole-surface P95 by at least 5% but lost local
fidelity, keep its global surface weight and kernel widths. The local noise target
is bounded by half the retained local noise and by the current global noise times
the retained good local/global noise ratio. Scale that target by the measured
retained/current marked P95 ratio clipped to [0.5, 1]; limit the decrease from the
last attempted local noise to fourfold per trial. This restores relative marked
weight rather than strengthening the whole surface again. Protection weight,
physical preservation limits and the good prefix remain fixed; the unsuitable
correction is excluded. These are nominal noise multipliers, not a normalization
theorem across different kernels and surface areas.

Unchanged kernel widths do not imply an identical discrete basis. Source/target
coverage is regenerated and can include points from a more refined material grid.
Staged geometry and control files bind the actual basis. This grouped contrast
remains under native qualification; it guarantees neither progress nor promotion
of a failed result.
A useful global gain can still be reused after Same local feedback. Previously
declared physical preservation limits do not shrink with surface-noise changes.

Automatic equivalence to a useful reference fit is still under prospective test.
Regression tests and numerical guards alone are insufficient. A single-form
regional success does not qualify another specimen, a shared cohort objective,
an atlas or PCA, and never substitutes for owner anatomical acceptance.

## Actual new-optimization checkpoint, 25 October 2026

The isolated development series now includes newly optimized native fields,
not only saved-field replay. Sealed native outputs are finite and nonzero;
compatible warm starts change their momenta. Actual staged objective geometry,
weights, controls, initializer and retained prefix are checked against each
declared proposal. A successful manual reference is used only by an independent
judge, never as a proposal input or numerical seed. Original owner journals and
the frozen source are verified separately after execution.

An earlier local contrast passes the production numerical guards, including
marked surfaces, transitions, retained surface shape, temporal sensitivity,
conforming spatial resolution and contact checks. It still fails the full
independent reference-equivalence comparison. Internal numerical suitability
therefore does not close the search acceptance gate. The useful measured result
can remain a numerical starting point for another declared contrast without
becoming an anatomical approval. The policy's user-facing explanation describes
measured progress from grouped settings, avoiding an unsupported causal claim
that resolution alone produced it.

The policy was revised during development on known data. This is not a blind
validation of an untouched policy on independent animals. Preparation, native
optimization, export and dense qualification retain their separate wall times;
interactive runtime suitability is also unqualified. The installed desktop
runtime and distributed installer remain unchanged. Seventy-six scoped
regressions passed for the functional changes; nineteen existing search tests
and Ruff/diff checks pass for the explanation correction. No new installer is
created from this checkpoint.

The subsequent full-surface preparation exposed its fixed-spacing control cap
before any native optimizer was dispatched. The declared bounded-spacing policy
above addresses that preparation failure without changing motion width or
surface weights. Thirty-four targeted search, regional-fit and frame tests pass,
including coverage of all source/target points, unchanged movement width and an
unattainable-budget rejection. Thirty-five related guided/refinement/study
workflow tests pass. Declaring this policy alone does not count as a new
contrast when earlier objective settings already have a result. A newly optimized
result on this bounded basis still needs the full independent geometry and
preservation checks.

## Subsequent bounded-basis checkpoint, 25 October 2026

The full-surface successor was actually optimized on its declared bounded basis.
It retains the good numerical prefix and starts a new zero residual; the rejected
correction and successful manual reference fields are not used as initializers.
Staged geometry, controls, objective weights and prefix identities agree with the
frozen proposal. Source and original owner journals remain unchanged after the
run. This extends new-optimization evidence, rather than saved-field replay.

The resulting endpoint passes outside-surface, shape, transition and temporal
checks. Contact flags remain after the declared conforming-refinement allowance,
so spatial sufficiency and numerical selection are false. The reference-equivalent
search acceptance gate remains open. A favorable surface-distance comparison
cannot override these failed checks or create anatomical approval.

A native relative-convergence message following a non-finite evaluation and an
accepted worsening is also insufficient evidence of tolerance convergence or
optimality. Finite stored parameters and a sealed zero return are different facts;
retain the raw stop evidence and assess the final geometry independently. No
optimizer recovery or modified native line-search rule is qualified here.

The independent surface-edge length proxy is sensitive to available graph
directions. Adding valid paths inside unchanged planar faces can materially
change that proxy without modifying a surface or field. Preserve the original
verdict and report such a same-surface diagnostic separately; neither graph
variant proves anatomical centreline length or homology.

Preparation, native optimization, export/dense qualification and independent
benchmarking are recorded separately. Repeated full-surface checks and refinement
are too costly in this experiment to qualify interactive runtime. The policy was
revised on known data, so this is still development evidence rather than a blind
independent-specimen test. No installer, installed runtime, cohort objective,
atlas or PCA is updated or approved by this checkpoint.

## Saved-result diagnosis and private prototypes, 26 October 2026

Separate a floating-point face-selection screen from exact triangle-pair
intersections. A selected-face count is not a pair count. A closed indexed mesh
with consistent winding does not establish that its mapped straight triangles
are disjoint, or that the underlying ambient map is valid. Compare temporal
grids on identical material points, connectivity and the complete field chain;
an earlier prefix-only replay cannot qualify a later residual.

A source-domain connectivity diagnostic changes permitted diagonals while
retaining point coordinates, ordered boundary segments and unrelated faces.
Check the existing domain itself rather than an idealized parent triangle when
roundoff and thin triangles affect containment predicates. Unchanged vertices
alone do not prove an identical three-dimensional piecewise-linear surface;
record a justified surface-change bound separately. A resource-limited contact
check has no completed contact verdict and cannot support a repair claim.

Private loader experiments retain immutable parsed arrays within one operation,
with fresh content hashes and actual file identities on reuse. This can avoid
repeated parsing without accepting stale geometry. Cache lifetime, retained
memory, cancellation and whole-pipeline parity remain separate requirements.
Repeated-load timings under a warm operating-system cache do not establish a
full-pilot speedup. Preparation, fitting, replay, contact refinement, export and
independent assessment need distinct clocks.

Before another native optimization, qualify finite objective/gradient checks,
exact accepted-vector binding and immutable best-accepted parameter snapshots.
Distinguish a native parameter checkpoint from the optimizer's complete internal
history. A non-finite trial, accepted cost regression or unbound export must not
become a successful convergence claim. Failing closed and retaining prior
evidence is an explicit numerical protocol change; pure synthetic observer
tests do not qualify it on the native runtime or authorize automatic recovery.

These diagnostics and private prototypes have not changed the production pilot,
installed runtime or acceptance bounds. A qualified new optimized result,
interactive runtime evidence and independent-specimen evaluation remain open.
