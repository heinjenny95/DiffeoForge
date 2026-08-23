# Experimental Strong-Wolfe line search

Status: **implemented as an explicit Engine 0.7 L-BFGS option; real-input
qualification remains prospective**

## Purpose

The Engine 0.6 L-BFGS candidate passed every frozen external endpoint gate on
five full-resolution Weevils, but its gradient norm oscillated while an Armijo
line search continued to accept the first proposed step. Armijo proves
sufficient objective increase; it does not require the directional derivative
to contract. Strong Wolfe adds that curvature condition without weakening the
existing objective safeguard.

## Configuration

```yaml
optimization:
  block_order: [momenta]
  direction_update: lbfgs
  line_search_condition: strong_wolfe
  armijo_constant: 0.0001
  strong_wolfe_curvature_constant: 0.9
  strong_wolfe_maximum_step_size: 10.0
```

`strong_wolfe` is currently restricted to the single momenta block already
supported by L-BFGS. The curvature constant must be greater than the declared
Armijo constant and smaller than one. The maximum step must be at least the
declared L-BFGS initial step.

For an ascent direction `d`, initial gradient `g0`, and candidate gradient
`g(a)`, an accepted step `a` must satisfy both:

```text
f(x + a d) >= f(x) + c1 a (g0 dot d)
abs(g(a) dot d) <= c2 (g0 dot d)
```

The deterministic search first expands the declared initial step by factors of
two up to the declared maximum, then bisects a bracket when required. Every
trial computes objective and gradient evidence; consequently it can cost more
than Armijo backtracking, which requests a candidate gradient only after the
objective condition passes. The existing maximum line-search evaluation count
remains a hard bound.

Invalid candidates become an upper bracket. If no finite step satisfies both
conditions, optimization terminates with `line_search_failed`. The Modern
workflow now fails before publishing an atlas/PCA bundle in that case, rather
than allowing a later zero-variance PCA error to obscure the real cause.

## Compatibility and evidence boundary

`armijo` remains the default for every legacy configuration. Engine 0.7 records
the line-search condition, curvature constant, maximum step, accepted steps,
and evaluation counts in its verified bundle and benchmark provenance.

Unit and workflow tests establish deterministic behavior, monotone accepted
objectives, bounded search, explicit failure, schema validation, and verified
bundle provenance. They do not establish a real-mesh convergence improvement.
Before any real Engine 0.7 result is computed, candidate curvature constants
must be frozen in immutable Weevil designs and compared with the unchanged
Engine 0.6 Armijo evidence and external gates.
