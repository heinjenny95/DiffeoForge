# Cohort-invariant shared-parameter steps

Status: **implemented explicitly in Modern Engine 1.1**

## Purpose

The deterministic-atlas objective is a sum over subjects. Each subject owns a
separate momenta tensor, but the template vertices and control points are shared
by the complete cohort. Their gradients therefore sum across subjects. A fixed
shared-parameter starter step becomes progressively more aggressive as cohort
size grows even when the per-subject geometry is unchanged.

Configuration v0.6 makes the step convention explicit:

```yaml
optimization:
  template_step_size: 0.01
  control_points_step_size: 0.01
  shared_step_scaling: inverse_subject_count
```

`inverse_subject_count` divides the declared initial template and control-point
steps by the validated subject count. It does not scale the subject-specific
momenta step. The complete summed objective, gradients, Armijo test, accepted
states, and deterministic subject order are unchanged. Only the initial units
of the two shared block searches become cohort invariant. Accepted effective
steps remain explicit in optimizer history and checkpoints.

`none` preserves the original behavior for legacy configurations. New
`modern-init` configurations select `inverse_subject_count`; fixed-reference
momenta-only qualifications record `none` because they do not update shared
blocks. The chosen convention is bound through workflow configurations,
bundles, benchmarks, prospective studies, checkpoints, and strict verification.

## Numerical tests

A unit test repeats one target four times and optimizes only the shared template
block. With inverse scaling, the four-subject accepted step is exactly one
quarter of the one-subject step and the resulting template vertices agree to
`1e-12` relative and absolute tolerance. Invalid implicit modes are rejected.

## Real 5k-Trochanter evidence

The source cohort contains 236 GPA-aligned subjects with 2,500 vertices and
5,000 triangles each, 210 control points, 20 time points, subject batch size
four, and the researcher-selected coarse/global/extreme-disparity model values.
Every benchmark design was frozen and verified before execution.

Engine 1.0 with unscaled shared steps reached the template block after one
accepted momenta decision but exhausted ten backtracking trials. It terminated
with `cycles_completed=0`, `failed_block=template`, 18 line-search evaluations,
23.199 minutes, and 496.20 MiB sampled peak RSS.

Engine 1.1 with inverse scaling completed the same 236-subject cycle with all
three blocks accepted, no failed block, 12 line-search evaluations, 26.225
minutes, and 503.41 MiB sampled peak RSS. The extra wall time is not a slowdown
comparison: Engine 1.0 stopped before completing the template/control-point
work. The successful run performed the complete cycle.

An independent 16-subject safety point completed all three blocks in 98.918
seconds with 12 line-search evaluations, compared with 133.280 seconds and 20
evaluations for the earlier unscaled observation. Final objectives differed by
approximately `2.5e-6` on a magnitude of about `2.59e3`.

These observations establish an engineering fix for one-cycle cohort-size
stability on this real dataset. They do not establish multi-cycle convergence,
scientific equivalence, a universal runtime forecast, or biological validity.
