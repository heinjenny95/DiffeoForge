# Modern optimizer convergence evidence

Status: **the Engine 0.5 compute hotpath is qualified on 16 full-resolution
subjects; Engine 0.6 L-BFGS materially improves real-input optimization and
external gates but is not yet qualified as converged**

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

## Scientific boundary

These are engineering registration and convergence diagnostics on one selected
16-subject cohort and one prospectively frozen five-subject cohort. They do not
prove atlas equivalence, biological validity, parameter suitability, safe
operation on 300 subjects, or that Deformetrica is the biological ground truth.
