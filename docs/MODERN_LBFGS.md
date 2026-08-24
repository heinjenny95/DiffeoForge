# Experimental Modern L-BFGS direction

Status: **single-block Engine 0.6 candidate prospectively qualified on five
full-resolution Weevils; exact multi-block Engine 1.2 implementation is stable
on a prospectively frozen 16-subject real 5k-mesh cohort, but no general speed
or convergence claim is established**

## Configuration

The existing optimizer remains the default for legacy configurations. New
configurations may declare:

```yaml
optimization:
  block_order: [momenta, template, control_points]
  direction_update: lbfgs
  lbfgs_history_size: 10
  lbfgs_curvature_tolerance: 1.0e-12
  lbfgs_initial_step_size: 1.0
```

Engine 1.2 retains an independent curvature history for each configured block.
The first visit to each block uses its declared starter step because that block
has no curvature evidence yet. Subsequent visits use a limited-memory two-loop
inverse-Hessian recursion for the equivalent minimization objective `-f`, then
an ascent Armijo or Strong-Wolfe line search starting from the separately
declared L-BFGS step. A pair is formed only from the accepted update and gradient
change of the same block while the other blocks are fixed for that decision;
histories are never mixed across incompatible tensor shapes.

Only curvature pairs satisfying

```text
s dot y > curvature_tolerance * ||s|| * ||y||
```

are retained. A non-finite or non-ascent quasi-Newton direction fails closed to
the ordinary gradient direction. Each retained block history is bounded by
`lbfgs_history_size`; storage does not grow with cycle count.

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

That next option is implemented separately in Engine 0.7; see
[Experimental Strong-Wolfe line search](MODERN_STRONG_WOLFE.md). Armijo remains
the default, so the Engine 0.6 trajectory stays available unchanged.

## Evidence boundary

Automated tests establish deterministic repeatability, monotone accepted
objectives, explicit schema and bundle provenance, bounded separate block
histories, exact split/resume equality, and a small reference problem on which L-BFGS
reaches the predeclared gradient tolerance while steepest ascent does not.
The frozen Weevil comparison establishes an engineering improvement on one
five-subject cohort. It does not establish general superiority, biological
validity, or readiness for 300-subject production.

Checkpoint v0.3 serializes every block history in a non-executable float64
tensor store with block-specific names, shapes, offsets, byte lengths, and
hashes. Completed-run continuation and guarded crash recovery can therefore
resume Engine 1.2 multi-block L-BFGS exactly at a committed cycle boundary.
Checkpoint v0.1 remains evidence-only; v0.2 remains verifiable and loadable for
its historical single-block contract. Cross-engine continuation still fails
closed.

The 16-subject real 5k-Trochanter Steepest baseline improved monotonically
through ten cycles (`30/30` accepted, objective `-296.658847331`) without
reaching stationarity. A separately frozen Engine 1.2 multi-block L-BFGS run
used the same subject prefix, 210 controls, 20 time points, batching and ten
cycles. It also accepted all `30/30` decisions with no failed block and improved
the final objective to `-185.491921828`. Its attachment term improved from
`-289.114990766` to `-173.764814864`, while the stronger deformation raised the
regularity cost from `-7.543856565` to `-11.727106963`. Measured optimizer time
was `912.739 s` rather than `753.033 s` and sampled peak RSS was `416.018 MiB`
rather than `413.454 MiB`. Thus this one run supports numerical stability and
greater progress per fixed cycle count, but not lower wall time, convergence,
biological validity, or general superiority. Benchmark v0.2 now preserves the
full per-decision trajectory so a prospectively selected shorter-cycle follow-up
can test whether the quality gain offsets the per-run cost.

The exact evidence directories are siblings below
`DiffeoForge Weevil Tests 2026-08-17` and begin with
`modern-reference-qualification-v0.6-5-subject-`. See
[Modern optimizer convergence evidence](MODERN_OPTIMIZER_CONVERGENCE.md).
