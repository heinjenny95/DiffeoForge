# Experimental Modern L-BFGS direction

Status: **implemented as an explicit Engine 0.6 momenta-only option; real-input
qualification remains prospective**

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

## Evidence boundary

Automated tests establish deterministic repeatability, monotone accepted
objectives, explicit schema and bundle provenance, bounded history, rejection
of unsupported multi-block use, and a small reference problem on which L-BFGS
reaches the predeclared gradient tolerance while steepest ascent does not.
Those tests do not establish superiority on real meshes.

Completed-run continuation and crash recovery deliberately reject L-BFGS for
now. Existing checkpoint formats store parameters and next step sizes but not
the curvature-pair history required to reproduce an uninterrupted L-BFGS
trajectory. A future format must serialize and verify that state before those
features can be enabled.

Real-input acceptance requires prospectively frozen Engine 0.6 Weevil designs,
strict workflow verification, and the unchanged external fixed-reference gates.
See [Modern optimizer convergence evidence](MODERN_OPTIMIZER_CONVERGENCE.md).
