# Experimental Strong-Wolfe line search

Status: **implemented and prospectively screened on five full-resolution
Weevils; no tested curvature constant improved the Engine 0.6 Armijo path**

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

## Prospective full-resolution screen

Four designs were created and verified before any Engine 0.7 result existed.
They used the same five approximately 10k-face Weevils, 20-cycle limit,
float64 CPU arithmetic, four threads, 1024 × 1024 recomputed Current tiles,
history size 10, initial L-BFGS step 1, and unchanged external gates. The only
screened difference was Armijo versus Strong Wolfe with `c2` equal to `0.9`,
`0.5`, or `0.1`.

The Engine 0.7 Armijo control reproduced the Engine 0.6 optimizer history
byte-for-byte (`e87bd3f14ca782211608e2705676b453b793979d042bccf2a930c6330415c7b4`).
Strong Wolfe `c2 = 0.9` produced that same history hash, final objective
`-27.209838936`, final gradient norm `68.377691283`, and 25 recorded
line-search positions. Its independently recomputed assessment also matched:
pooled residual ratio `0.954123362`, 5/5 subject passes, and normalized
cross-engine p95 `0.010605541`. Both workflows and assessments passed strict
verification.

`c2 = 0.5` and `c2 = 0.1` each exhausted the frozen ten-evaluation search on
the first momenta decision. Both failed explicitly with no final destination
and no atlas/PCA bundle. Thus `0.9` adds gradient-evaluation cost without
changing the trajectory, while the tested stricter constants are incompatible
with the frozen starting step and search budget. Engine 0.7 does not replace
Armijo as the recommended real-input option.

## Compatibility and evidence boundary

`armijo` remains the default for every legacy configuration. Engine 0.7 records
the line-search condition, curvature constant, maximum step, accepted steps,
and evaluation counts in its verified bundle and benchmark provenance.

Unit and workflow tests establish deterministic behavior, monotone accepted
objectives, bounded search, explicit failure, schema validation, and verified
bundle provenance. The frozen Weevil screen is negative engineering evidence,
not proof that Strong Wolfe is unsuitable for every cohort or search budget.
The exact evidence directories are siblings below
`DiffeoForge Weevil Tests 2026-08-17` and begin with
`modern-reference-qualification-v0.7-5-subject-`.
