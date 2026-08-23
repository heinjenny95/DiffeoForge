# Experimental Modern L-BFGS direction

Status: **implemented and prospectively qualified as a materially better
Engine 0.6 momenta-only candidate on five full-resolution Weevils; the declared
absolute-gradient convergence gate is not yet met**

## Configuration

The existing optimizer remains the default for legacy configurations. New
configurations may declare:

```yaml
optimization:
  block_order: [momenta]
  direction_update: lbfgs
  lbfgs_history_size: 10
  lbfgs_curvature_tolerance: 1.0e-12
  lbfgs_initial_step_size: 1.0
```

`lbfgs` is currently rejected for multi-block optimization. The first decision
uses the declared momenta step because no curvature evidence exists yet.
Subsequent directions use a limited-memory two-loop inverse-Hessian recursion
for the equivalent minimization objective `-f`, then an ascent Armijo line
search starting from the separately declared L-BFGS step.

Only curvature pairs satisfying

```text
s dot y > curvature_tolerance * ||s|| * ||y||
```

are retained. A non-finite or non-ascent quasi-Newton direction fails closed to
the ordinary gradient direction. The retained history is bounded by
`lbfgs_history_size`; it does not grow with cycle count.

## Prospective full-resolution evidence

Three fixed-reference designs were created and verified before any Engine 0.6
result existed. All used the same five approximately 10k-face Weevil subjects,
float64 CPU arithmetic, four threads, 1024 × 1024 recomputed Current tiles, and
the unchanged Deformetrica-bound external gates. The designs declared a
20-cycle steepest-ascent control, a 20-cycle L-BFGS candidate, and an
independent 40-cycle L-BFGS reserve run. Every workflow and every assessment
passed strict verification, including recomputation of all external metrics.

| Run | Final objective | Final / minimum gradient norm | Pooled residual ratio | Subject pass fraction | Cross-engine p95 / diagonal |
| --- | ---: | ---: | ---: | ---: | ---: |
| Steepest, 20 cycles | `-43.300625063` | `322.889990219` / `295.395705289` | `1.145717736` | `0.8` | `0.013369104` |
| L-BFGS, 20 cycles | `-27.209838936` | `68.377691283` / `52.917992173` | `0.954123362` | `1.0` | `0.010605541` |
| L-BFGS, 40 cycles | `-15.255475289` | `129.152175750` / `34.592042331` | `0.798957722` | `1.0` | `0.017012439` |

At equal cycle count, L-BFGS reduced the final gradient norm by about 79%,
improved the final objective by `16.090786127`, changed the pooled residual
ratio from a passing `1.1457` to `0.9541`, and raised the subject pass fraction
from 4/5 to 5/5. The 40-cycle reserve improved the internal objective and pooled
external residual ratio further. These improvements did not come from relaxed
gates: the designs retained the same limits and the same bound references.

All three assessments remain `inconclusive_not_converged` because the declared
absolute gradient tolerance is `0.0001`. The 40-cycle gradient oscillated after
reaching its minimum and ended higher despite continued monotone objective
improvement. More cycles alone are therefore not accepted as the next fix. The
next candidate must prospectively test a curvature-aware line search or another
explicitly versioned convergence strategy.

## Evidence boundary

Automated tests establish deterministic repeatability, monotone accepted
objectives, explicit schema and bundle provenance, bounded history, rejection
of unsupported multi-block use, and a small reference problem on which L-BFGS
reaches the predeclared gradient tolerance while steepest ascent does not.
The frozen Weevil comparison establishes an engineering improvement on one
five-subject cohort. It does not establish general superiority, biological
validity, or readiness for 300-subject production.

Completed-run continuation and crash recovery deliberately reject L-BFGS for
now. Existing checkpoint formats store parameters and next step sizes but not
the curvature-pair history required to reproduce an uninterrupted L-BFGS
trajectory. A future format must serialize and verify that state before those
features can be enabled.

The exact evidence directories are siblings below
`DiffeoForge Weevil Tests 2026-08-17` and begin with
`modern-reference-qualification-v0.6-5-subject-`. See
[Modern optimizer convergence evidence](MODERN_OPTIMIZER_CONVERGENCE.md).
