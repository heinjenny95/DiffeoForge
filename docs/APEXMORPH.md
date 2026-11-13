# Apexmorph research and acceptance

Apexmorph is the name of the experimental engine called Modern in earlier
benchmarks and saved runs. Its development priority is to fit several small
teeth and long, thin projections on the same surface, including cohorts whose
members differ substantially in projection length and prominence.

## How to judge a fit

1. Require acceptable overall shape for each specimen and valid mesh topology.
   Declare the surface and topology limits before fitting. Report both the
   whole-surface P95 and RMSE so a local gain can be weighed against any change
   elsewhere on the surface.
2. Within those limits, prefer fits that recover more small features and
   preserve ones that already pass. Measure tip location and the surrounding
   surface in both directions. Where adjacent branches could be confused,
   also check whether the fitted patch belongs to the intended branch.
3. Include forms with short, long, and absent prominences. Measure unwanted
   protrusions at absent sites. Report each feature and each specimen before
   pooling, and separate geometry checks from anatomical review.
4. Report runtime, accepted updates, optimizer evaluations and memory at the
   achieved quality. Additional compute is acceptable when it improves the
   anatomical fit within the declared run budget.

Landmarks may establish the common alignment. Independent feature annotations
are reserved for evaluation. A diffeomorphic deformation of a shared template
can reduce a projection to a less prominent shape while preserving connectivity.
It cannot change template topology, and a small point distance alone does not
establish anatomical homology. True topological differences and ambiguous
branch correspondences require separate evaluation.

## First research contrast

Test a finer Varifold surface term alongside the existing whole-surface term,
using the same diffeomorphic trajectory and deformation regularity. Start the
two arms from the same field and use the same explicit optimizer budget and
initialization. Score every specimen against the original target geometry with
the same export protocol. Compare both short and long projections and check
whether previously recovered features survive. The candidate remains a
research experiment until it meets the declared acceptance criteria.

Use known panels to develop the method. Freeze the recipe and the acceptance
criteria before testing on new forms. A surface-error detector can help locate
misses, but it must demonstrate adequate feature recall and manageable alert
burden before it can decide which regions receive extra fitting weight.
