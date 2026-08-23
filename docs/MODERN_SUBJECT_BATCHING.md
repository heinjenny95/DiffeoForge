# Modern Engine subject batching

Status: **implemented as an explicit opt-in execution mode in Engine 1.0**

## Purpose

Large cohorts should not require one simultaneous autograd graph containing
every subject. Modern Engine 1.0 therefore accepts:

```yaml
optimization:
  subject_batch_size: 4
```

The value is optional. `null` or an omitted key preserves the full-cohort Engine
0.9 path. A positive value evaluates subjects in deterministic consecutive
batches. Objective, attachment, regularity, residual, and gradient contributions
are accumulated in frozen subject order.

For a momenta block, batch gradients are concatenated back into the declared
subject order. Template and control-point gradients are shared across subjects
and are summed in that same order. Line-search decisions still use the complete
cohort objective; this is not stochastic or mini-batch optimization.

## Memory and work trade-off

The batched path first computes the complete objective without retaining an
autograd graph. When a gradient is requested, it recomputes each subject batch,
immediately differentiates it, detaches its contribution, and releases that
batch before moving on. This bounds retained autograd state but adds one
objective recomputation per requested gradient. Optimizer reports record those
extra objective evaluations explicitly.

The CLI fixed-reference design command exposes `--subject-batch-size`. The
effective workflow configuration, optimizer settings, benchmark configuration,
bundle, hashes, and continuation binding all retain the chosen value. Direct
callers default to the legacy unbatched path.

## Real 16-subject engineering observation

After implementation, one fresh-process, one-cycle, full-resolution Weevil
optimizer observation compared the unchanged full-cohort path with subject
batch size four. Both reports strictly verified. This was an implementation
measurement, not a pre-frozen comparative study:

| metric | full cohort | batch size 4 | candidate / baseline |
|---|---:|---:|---:|
| optimizer wall time | 273.826 s | 295.114 s | 1.078 |
| sampled peak RSS | 1117.41 MiB | 495.43 MiB | 0.443 |
| sampled RSS growth | 841.29 MiB | 220.34 MiB | 0.262 |
| objective evaluations | 9 | 11 | explicit recomputation |
| gradient evaluations | 2 | 2 | unchanged |

Both reports bind Engine implementation `1.0` and strictly verify. Final momenta
were byte-identical. Final objective and attachment components differed only at
approximately `5.7e-14`, consistent with the declared change
in floating-point summation grouping; final regularity was identical. Unit and
workflow tests cover all three parameter blocks and require numerical agreement
at `1e-12` relative and absolute tolerance.

The observation supports a larger prospective scaling study. It does not prove
linear scaling, peak-memory guarantees, 300-subject feasibility, convergence,
atlas equivalence, or biological validity.
