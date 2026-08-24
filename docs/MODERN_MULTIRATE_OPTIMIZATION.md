# Experimental multi-rate atlas optimization

Status: **Engine 1.3 implementation complete; real-cohort candidate not yet
qualified**

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
complete-cycle resume. They do not establish that repeated Momenta visits are
faster, converge, improve biological correspondence, or are suitable for 300
subjects. The first real-cohort configuration must be frozen and evaluated
against predeclared objective, time, validity, and trace gates before any
efficiency statement is made.
