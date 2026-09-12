# Modern Engine subject batching

Status: **serial memory-bounded execution implemented in Engine 1.0; explicit
deterministic parallel batch execution implemented in Engine 1.4**

## Purpose

Large cohorts should not require one simultaneous autograd graph containing
every subject. Modern Engine 1.0 therefore accepts:

```yaml
optimization:
  subject_batch_size: 4
  subject_batch_workers: 2
```

The value is optional. `null` or an omitted key preserves the full-cohort Engine
0.9 path. A positive value evaluates subjects in deterministic consecutive
batches. Objective, attachment, regularity, residual, and gradient contributions
are accumulated in frozen subject order.

`subject_batch_workers` defaults to one. Engine 1.4 permits `2` through `64`
only when a finite `subject_batch_size` is declared. Independent batches may
then execute concurrently on CPU worker threads, but their results are always
collected and reduced in the original batch order. Parallel and serial runs
with the same batch grouping therefore retain the same floating-point reduction
order; tests require exact optimizer histories and exact final tensors. Changing
the batch size can still change last-order floating-point bits because it changes
the grouping of the reductions.

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

Engine 1.4 additionally stores the worker count in the effective configuration,
optimizer settings, workload and benchmark evidence, result bundle, and
complete-cycle checkpoint binding. Resume and guarded recovery reject a worker
count or batch-size mismatch. Historical evidence without the worker field means
one worker.

The thread count in `runtime.threads` and `subject_batch_workers` are separate:
the former controls PyTorch work inside one batch, while the latter controls how
many independent subject batches may be in flight. More workers are not assumed
to be faster because nested CPU parallelism and memory bandwidth can dominate.
Adoption therefore requires a prospective real-cohort screen and a separate
full-cohort confirmation. Engine 1.4 has passed both on the development Ryzen 9
7950X: two workers were bit-exact and reduced the 236-subject/two-cycle optimizer
time by 21.55%, from 65.714 to 51.555 minutes. Sampled peak RSS increased to
780,652,544 bytes and four workers exceeded the predeclared screen memory gate.
The result is hardware/workload-specific, so one worker remains the generated
cross-machine default. See the
[prospective gate](MODERN_ENGINE14_PARALLEL_BATCH_GATE.md).

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
