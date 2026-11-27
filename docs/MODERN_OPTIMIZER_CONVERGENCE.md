# Modern optimizer convergence evidence

Status: **the Engine 0.5 compute hotpath is qualified on 16 full-resolution
subjects; Engine 0.8 L-BFGS with corrected relative-objective stopping passed
its prospective five-subject convergence and fixed-reference engineering
gates**

## Frozen evidence

A fixed-reference design selected 16 approximately 10k-face Weevil subjects
before any Modern result existed. It reused the completed Deformetrica pilot
order, excluded seven candidates that failed the declared topology gates, and
filled the remainder deterministically by filename. The design fixed the
Deformetrica estimated template and control points, optimized only subject
momenta, used Engine 0.5 with float64 CPU arithmetic and 1024 × 1024 recomputed
Current tiles, and predeclared all external endpoint gates.

The initial three-cycle workflow completed and passed strict workflow
verification. Its objective improved monotonically from `-612.108853308` to
`-233.805976252`, but its final gradient norm was `754.143472889` against the
declared `0.0001` tolerance. The independently recomputed fixed-reference
assessment therefore returned `inconclusive_not_converged`. The cross-engine
reconstruction-distance gate passed, while the pooled Modern-to-Deformetrica
external-residual ratio was `1.769105946` against a maximum of `1.2`; no subject
passed the predeclared `1.25` individual ratio gate.

A successor design was then frozen from the exact hash-bound parent endpoint
before its result existed. Ten additional cycles all accepted at the first
line-search evaluation and improved the objective monotonically from
`-233.805976252` to `-122.957442692`. The external assessment improved to a
pooled residual ratio of `1.282997253`, and 9 of 16 subjects passed their
individual gate. The cross-engine distance improved from `0.029486696` to
`0.015377995`, below the frozen `0.05` maximum. The assessment and its external
metrics passed strict recomputation-based verification.

The successor remains `inconclusive_not_converged`. Its observed gradient norm
fell from `668.525541118` to a minimum of `561.259175211` after six successor
cycles, then rose to `596.007663167` while the objective continued to improve.
This is evidence that simply repeating the accepted constant steepest-ascent
step is not an adequate convergence strategy. It is not evidence that the
gradient tolerance should be relaxed after seeing the result.

## Engineering implication

The next optimizer must be an explicit, versioned configuration choice and
must retain the existing steepest-ascent trajectory for old configurations.
Its direction, line-search work, convergence criterion, state needed for
continuation, and checkpoint behavior must be recorded. A prospective
fixed-reference design must exist before a real-input result is computed.

Limited-memory BFGS is implemented as the next Engine 0.6 candidate because it
uses gradient-history curvature to avoid the zig-zag behavior of fixed steepest
ascent while keeping memory proportional to a declared small history size.
Its prospectively frozen five-subject comparison passed every unchanged
external endpoint gate and reduced the 20-cycle final gradient norm from
`322.889990219` to `68.377691283`. The pooled external residual ratio improved
from `1.145717736` to `0.954123362`, and the subject pass fraction improved from
4/5 to 5/5. An independently frozen 40-cycle reserve reached a lower minimum
gradient of `34.592042331` and a pooled ratio of `0.798957722`, but its final
gradient rose to `129.152175750`. Every workflow and assessment passed strict
verification and external-metric recomputation.

The unchanged `0.0001` absolute-gradient gate therefore continues to reject all
real-input runs as not converged. The next engineering step is a separately
versioned curvature-aware line-search experiment; additional cycle count alone
is not treated as evidence of convergence.
See [Experimental Modern L-BFGS direction](MODERN_LBFGS.md).

That Engine 0.7 Strong-Wolfe screen did not improve the trajectory: `c2 = 0.9`
was byte-identical to Armijo, while `c2 = 0.5` and `0.1` exhausted the frozen
first-step search budget without publishing a result. During this audit the
installed Deformetrica 4.3 source also confirmed that its
`convergence_tolerance` is an objective-change ratio, not an absolute gradient
norm: it compares the latest accepted objective change with the cumulative
change since initialization. Mapping that value to Modern
`gradient_tolerance` was therefore semantically incorrect. A new versioned
Modern stopping criterion must reproduce and record the objective-change test
while retaining the absolute gradient norm as a diagnostic rather than
silently weakening it after observing these results.

Engine 0.8 implements that correction as an optional, separately recorded
`relative_objective_tolerance`. New fixed-reference designs map the source
Deformetrica value to this field, set the unrelated absolute
`gradient_tolerance` to zero, and continue recording every gradient norm as a
diagnostic. Legacy configurations omit the field and retain their exact prior
termination behavior. See
[Modern relative-objective stopping semantics](MODERN_OBJECTIVE_STOPPING.md).

The first Engine 0.8 result remained prospective until its design had frozen
the five subjects, fixed template and control points, L-BFGS/Armijo settings,
150-cycle ceiling, `0.0001` relative-objective tolerance, and unchanged
external gates. It stopped at cycle 84: the ratio was
`0.00025156877665148848` at cycle 83 and
`0.000069593162405623017` at cycle 84. All 84 decisions were accepted and the
objective improved monotonically from `-189.78482461065454` to
`-8.926917073610918`.

The independently recomputed fixed-reference assessment passed every frozen
gate. Its pooled Modern-to-Deformetrica external-residual ratio was
`0.6936240097772872`, all 5/5 subjects passed, and cross-engine reconstruction
distance was `0.01896835023041072`. Both the workflow and assessment passed
strict verification. This resolves the five-subject optimizer-stopping
qualification without weakening the gradient diagnostic after observing a
result.

## Scientific boundary

These are engineering registration and convergence diagnostics on one selected
16-subject cohort and one prospectively frozen five-subject cohort. The
five-subject Engine 0.8 result passes its declared engineering gates, but it
does not prove atlas equivalence, biological validity, parameter suitability,
safe operation on 300 subjects, or that Deformetrica is the biological ground
truth.
