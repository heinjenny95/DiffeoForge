# Experimental multi-rate atlas optimization

Status: **Engine 1.3 implementation complete; first frozen real-cohort
efficiency gate passed**

## Motivation

An atlas has many subject-specific Momenta but only one shared template and one
shared control-point set. Updating every block exactly once per outer cycle is
transparent, but it need not allocate work efficiently. In the frozen Engine
1.2 seven-cycle real 5k-Trochanter trace, Momenta decisions supplied about
`4387.959` objective gain, compared with `580.012` from template decisions and
`601.847` from control-point decisions.

Engine 1.3 therefore adds one explicit experimental setting:

```yaml
optimization:
  block_order: [momenta, template, control_points]
  momenta_updates_per_cycle: 2
```

The legacy and generated default is `1`. Values from 1 through 100 are accepted
by reviewed workflow configurations. A value other than 1 is invalid when
Momenta are absent from `block_order`.

## Exact schedule

The configured unique block order remains the parameter-set declaration. One
outer cycle expands it deterministically by visiting Momenta consecutively the
declared number of times and every other block once. The example above means:

```text
momenta -> momenta -> template -> control_points
```

L-BFGS uses the same bounded Momenta curvature history for the consecutive
Momenta visits. Template and control points retain their own separate histories.
Every candidate still passes the declared Armijo or Strong-Wolfe line search;
no step is silently accepted. Gradient and relative-objective stopping are
evaluated only after a complete expanded cycle.

## Provenance and recovery

The normalized setting is recorded in optimizer settings, result bundles,
workload plans, prospective optimizer designs, raw benchmark reports, and
checkpoint bindings. Live progress and workload bounds use the expanded number
of block decisions rather than the number of unique parameter blocks.

Complete-cycle checkpoint state already stores one history per unique block.
Checkpoint v0.3 now optionally binds `momenta_updates_per_cycle`; its absence in
historical Engine 1.2 checkpoints means `1`. Engine identity prevents a prior
checkpoint from being resumed under Engine 1.3 as if scheduling were unchanged.
Engine 1.3 split/resume tests reproduce the uninterrupted multi-rate trajectory
exactly.

## Evidence boundary

Unit and end-to-end tests establish deterministic ordering, monotone accepted
objectives, exact work counters, progress bounds, strict artifacts, and exact
complete-cycle resume. The first frozen 16-subject real 5k-Trochanter gate used
five cycles of `momenta, momenta, template, control_points`. It accepted all 20
decisions, reached objective `-160.39978136827878` in 542.635 seconds, and used
413,716,480 bytes sampled peak RSS. Against the gate-bound Engine 1.1
ten-cycle Steepest baseline, this was 27.94% less optimizer time and a better
objective than the required `-296.6588473308086`. See
[the frozen Engine 1.3 gate](MODERN_ENGINE13_MULTIRATE_GATE.md).

A second gate is frozen separately for two multi-rate cycles on all 236
available real 5k-Trochanters against the strictly verified Engine 1.1
three-cycle full-cohort baseline. See
[the Engine 1.3 full-cohort gate](MODERN_ENGINE13_FULL_COHORT_GATE.md).

That full-cohort gate accepted all eight decisions and passed its objective,
trace, and memory thresholds, reaching objective `-8545.854488271007` with
542,019,584 bytes sampled peak RSS. It failed the time threshold: 65.714
minutes was 35.10% slower than the 48.640-minute Engine 1.1 baseline. Momenta
supplied 93.0% of the total accepted objective gain, and the second Momenta
visit of cycle two was the first record to exceed the baseline objective.
Consequently, the schedule remains a useful quality candidate, but serial
full-cohort evaluation is not an efficiency-qualified implementation.

The 16-subject pass and 236-subject time failure do not establish convergence, a universal schedule,
improved biological correspondence, or suitability for 236/300 subjects. The
optimizer stopped at the declared five-cycle cap. Larger-cohort scaling,
repeatability beyond the deterministic single repeat, and full atlas-output
assessment remain separate gates.
