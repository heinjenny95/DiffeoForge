# Fixed coordinates for protected regional optimization

New protected single-form objectives prepare a fixed positive-definite coordinate
map from their explicit controls, movement width, focus scale and dense fixed
points. The native coefficients are `x = x0 + B z`; native objective/gradient
values are evaluated at `x`, and the chain-rule gradient is `B.T g`. Native
L-BFGS-B, likelihood equations and physical accepted states remain in use. This
addresses stiff mixed local-fit/preservation scales that can make useful steps
very small. It does not guarantee a fit or a speedup on a new anatomy.

The matrix and control identities are hash-bound, staged with the engine and
recorded in its guard policy. Nonfinite, nonsymmetric or non-positive matrices,
unknown preimported optimizer aliases and changed controls fail closed. Cold and
warm native imports are supported through their exact known aliases. The finite
accepted-state guard still sees the physical objective, gradient, parameters and
callbacks. Final physical gradients are returned from the exact native cache.

The transformed gradient stopping threshold is conservatively scaled by
`lambda_min(B) / sqrt(3N)`. Thus satisfying it cannot weaken the original native
physical infinity-gradient threshold. The original function-change tolerance,
iteration/review budgets and geometry/Retain approval bounds are unchanged.
Coordinate trajectories and stopping behavior can differ; this is not a claim of
identity with the previous unconditioned optimization path.

Automatic preparation is confined to newly prepared, frozen regional plans with
explicit fixed protection and the current material-selection contract. Ordinary
cohort staging clears the complete coordinate marker. Existing plans are not
upgraded by reading/rendering them. Numerical extensions preserve their existing
coordinate contract; legacy extensions retain their old coordinates. No saved
owner field or run is changed.

Verification: 55 targeted source cases pass, including seven new preparation,
positive-basis/identity, budget, legacy/successor, chain-rule/callback/physical
result and alias-rejection cases. Lint passes. New exact-source public native
CPU trials with a 20-iteration cold cap and a two-iteration warm cap returned zero,
preserved the strict fixed patch and exported finite guard-bound fields. The warm
seed differed from its saved guard vector only by about 1.2e-16 of native text
serialization roundoff. These controlled cases qualify the implementation, not
anatomical suitability or prospective speed. Installed runtime remains dev175
until verified delivery.
