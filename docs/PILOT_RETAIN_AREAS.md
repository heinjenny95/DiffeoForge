# Retain-area protection: dense constraints and early review checks

The owner reported a fitting trade-off where two projections improved while a
previously correct marked projection disappeared. Inspection showed that an
explicit Retain area was represented by a few points from the automatic global
sample and shared the soft outside-protection weight. Even those points could
move far beyond the declared post-check bound during optimization. Navigation
qualification did not establish geometric preservation.

dev175 changes newly prepared regional trials with explicit fixed-position areas.
Every marked retained material vertex and the vertices of incident triangles are
included, independently of the global sample. A separate native Landmark object
uses its own declared noise scale, at most one quarter of the unchanged movement
bound (target diagonal times 1e-4). The global outside-protection term remains.
Empty or unrepresented Retain patches produce an actionable starting-fit/area
error instead of receiving a vacuous preservation pass. Assets, vertex coverage,
reference scale, weight and bounds are hash-bound in the generated plan.

Retain remains relative to the selected saved starting fit. The software does not
infer that the latest displayed attempt is necessarily the desired protected
shape, splice two independently fitted fields together or approve anatomy.
The chosen starting fit is displayed in the working-fit card. To restore a
projection from an earlier state, that inspected saved fit remains selectable.

New feedback reading also follows each Retain mark back to the inspected saved
fit where it was introduced. A whole-fit fallback caused by an outside-quality
regression must not silently change that local reference. A Better decision can
identify the numerical source without creating anatomical approval. Retain marks
introduced on a nonpreferred whole fit require an explicit working-fit choice;
the software does not automatically reuse a known bad whole field. Inherited
marks keep their source when a later attempt is judged worse. A newer explicit
working-fit choice takes precedence. Marks referring to several different fields
require one working fit and confirmation together, rather than field splicing.
The working-fit card explains this choice and retains its direct inspection/edit
action. Same-objective continuation and reuse of a newer seed must bind the same
retained run and its manifest; a legacy objective protecting an older fallback is
not treated as equivalent. Existing journals, approvals and saved fields are read
without rewriting them.

The post-check now uses maximum displacement over the whole retained patch,
including the refined material grid, instead of checking only the old sampled
ids. Intermediate review also checks the retained vertices and prominently reports
violations or unavailable protection evidence. Export/check remains accessible;
a failed protection check is not labelled passed and does not approve an atlas.
Legacy prepared objectives and completed evidence are not rewritten. Where a
legacy preview has the matching full retained material mesh, the new reader can
audit its whole marked patch without rerunning an optimizer.

The native optimizer and its equations are unchanged. This is a change to the
explicit regional constraint geometry/weight, not an exact hard-constrained
solver or a proof that every requested combination is feasible. A new result must
still satisfy the unchanged displacement bound and geometry/integration guards.
Iteration/time allowances, convergence tolerance and scientific approval gates
are not relaxed. The first review remains after ten active minutes.

Qualification: 109 unique source cases (eight new dense-retention/UI cases), lint,
and new bounded public three-part native CPU and CUDA/KeOps trials with one CPU
thread. In the CPU trial, with Float32/37-point RK2 and a 60-iteration cap,
the intended part's mean vertex error
fell from 0.2 to 0.002380439 model units. The marked part's maximum movement was
3.891103e-5 (within its declared bound); the other unchanged part moved at most
1.666434e-5. The native run returned zero with no numerical-guard violation. This
is controlled engineering evidence, not prospective anatomy, speed or convergence
qualification for an owner specimen. Owner trials were not restarted or changed.
The GPU trial reduced intended-part mean error to 0.001321217, with marked-part
maximum movement 7.592891e-6 and other-part movement at most 1.058296e-5. It also
returned zero with no guard violation. CPU and GPU fields were independently
evaluated at 73 time points without optimizer updates; complete retained-patch,
outside/local and no-new-intersection checks passed on both. This is not a native
CPU/GPU trajectory-identity or ant anatomical-quality claim.
dev175 is verified installed; see [delivery evidence](V175_DELIVERY.md).
