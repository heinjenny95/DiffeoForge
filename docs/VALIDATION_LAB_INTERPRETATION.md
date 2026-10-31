# Interpreting Validation Lab and landmark comparisons

Validation Lab compares a frozen, limited set of candidate configurations. It
does not certify biological homology, fine-detail recovery, or a universal
parameter optimum. This note clarifies the existing implementation; it does
not change the metric, decision rule, or any completed result.

## Separate completion, numerical preference, and scientific validity

- Completed, converged runs with no reported invalid faces passed the collected
  execution and geometric gates. Optimizer convergence is not anatomical review.
- Training/resampling preference describes sensitivity to the declared cohort
  changes. Overlapping resamples are not independent replication experiments.
- Fixed-template holdout registration estimates new subject momenta while
  retaining the training template and control points. This tests those frozen
  models on reserved subjects; check upstream alignment and pilot provenance
  before describing the entire pipeline as independently held out.
- Anatomical accuracy and retention of biologically relevant differences need
  independent criteria, not merely a preferred candidate in the report.

## Read the equivalence margin and tie-break before counting wins

The current rule retains candidates within an absolute surface-error margin of
the best candidate. Without a supplied smallest relevant feature, this margin
is 0.5% of the template diagonal: a numerical fallback, not an anatomically
validated equivalence threshold. When a feature is supplied, the rule uses 5%
of that feature length; this is still a declared design choice, not automatic
evidence of biological equivalence.

Among surface-equivalent candidates, the holdout assessment compares each
candidate's **pooled cohort distortion**, not a separate distortion statistic
for the current subject. Distortions within 2% of the lowest value are treated
as equivalent before preferring the smoother deformation kernel. Consequently,
if all candidates are surface-equivalent for every subject, the same pooled
tie-break can assign every subject to one candidate. Such unanimous support
must not be reported as independently superior surface fits for every subject.

Report the raw surface errors, margin, pooled distortion, and rule-based support
separately. Lower distortion alone does not establish better fine-detail recovery.
The implementation is in
[`reference_holdout_study.py`](../src/diffeoforge/reference_holdout_study.py)
and [`reference_validation.py`](../src/diffeoforge/reference_validation.py).

## Understand the surface metric's sampling

Metric v0.2 uses deterministic index-spaced samples of at most 3,000 source
vertices and 5,000 target triangles in each direction, then summarizes the
vertex-to-sampled-triangle distances. It is not an exact distance to every
triangle of the full target, and the sampling is not area-weighted. Sampling
can therefore influence comparisons and miss localized errors. This evaluation
limit does **not** mean that atlas inputs were decimated to 5,000 triangles.
See [`reference_validation_metrics.py`](../src/diffeoforge/reference_validation_metrics.py).

## Landmark PCA is a different comparison target

Distinguish a comparison of estimated versus manual landmark configurations
from a comparison of surface-deformation momenta versus landmark coordinates.
For example, [Zhang et al., Automated landmarking via multiple templates](https://doi.org/10.1371/journal.pone.0278035)
evaluates automated landmark estimates against manual landmarks. Its agreement
statistics are not a directly transferable acceptance threshold for a
deformation-space ordination.

For a meaningful comparison, match specimen identities, included anatomy,
alignment/scaling, landmark definitions, and analysis dimensions. LDDMM metric
PCA weights initial momenta by the deformation kernel; RBF kPCA adds its own
bandwidth-dependent representation. Neither is simply PCA of landmark positions.
PC signs or ordering alone should not determine agreement. Compare distances
and subspaces as well, without assuming that every discrepancy is an arbitrary
axis rotation or evidence that one representation is biologically superior.

Possible explanations to test include anatomical weighting, kernel locality,
regularization, differing cohorts, alignment, and inconsistent mesh content or
registration quality. These are hypotheses until checked. Landmark coordinates
used for prealignment are not independent validation labels. Pairwise distances
also share specimens; do not attach naive independent-observation significance
tests to all specimen pairs.

## Next evidence, not automatic reruns

Inspect existing reconstructions in relevant anatomical regions and flagged
cases, audit sampling and tolerance suitability, and use independent anatomical
criteria where available. A parameter effect on surface error or distortion
does not demonstrate improved landmark-PC agreement until that comparison is
actually recomputed. Do not tune parameters or thresholds after inspecting
holdout outcomes and continue calling the same holdout untouched. Any further
confirmatory design must account for its prior use.
