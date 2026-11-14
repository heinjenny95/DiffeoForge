# Apexmorph research and acceptance

Apexmorph is the name of the experimental engine called Modern in earlier
benchmarks and saved runs. Its primary local fitting target is long, thin
projections near the distal end of a shape. Cohorts may differ substantially in
projection number, length, and prominence. Small teeth are a secondary fitting
priority.

## How to judge a fit

1. Require acceptable overall shape for each specimen and valid mesh topology.
   Declare the surface and topology limits before fitting. Report both the
   whole-surface P95 and RMSE and measure the body separately to detect any
   loss of fit outside the projections.
2. Within those limits, prioritize recovery of long, thin distal projections
   and preservation of projections that already pass. Measure tip position,
   base-to-tip length and direction, and surface fit in both directions from
   base to tip. Check that adjacent projections remain distinct and that a
   projection reaches the target tip with a plausible thickness. Report small
   tooth fit as a secondary outcome.
3. Include forms with short, long, and absent prominences. Measure unwanted
   protrusions at absent sites. Report each feature and each specimen before
   pooling, and separate geometry checks from anatomical review.
4. Report runtime, accepted updates, optimizer evaluations and memory at the
   achieved quality. Additional compute is acceptable when it improves the
   anatomical fit within the declared run budget.

Landmarks may establish the common alignment. Independent feature annotations
are reserved for evaluation. A diffeomorphic deformation can change how many
projections are visible on a shared template while preserving its topology.
Assess the fitted projections against the target geometry. Biological homology
requires independent anatomical evidence.

## Fixed-reference comparisons

Compare a candidate objective with the existing whole-surface objective using
the same deformation model and regularity. Start both arms from the same
field and use the same explicit optimizer budget and export protocol. Score
each specimen against the original target geometry. A continuation from a
saved fit tests recovery and preservation of projections from that fit. Use a
comparison from the shared initial state to establish performance on a full
fit. The candidate remains experimental until it meets the declared acceptance
criteria.

Use known panels to develop the method. Freeze the recipe and the acceptance
criteria before testing on new forms. A surface-error detector can help locate
misses, but it must demonstrate adequate feature recall and manageable alert
burden before it can decide which regions receive extra fitting weight.
