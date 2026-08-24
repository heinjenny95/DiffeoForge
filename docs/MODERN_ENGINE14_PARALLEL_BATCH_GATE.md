# Engine 1.4 parallel-subject-batch gate

Status: **PROSPECTIVE; no Engine 1.4 result existed when frozen**

## Question

Can deterministic concurrent evaluation of already memory-bounded subject
batches reduce optimizer time on the real 5k-Trochanter workload without
changing a single result bit?

This is a same-machine engineering screen followed, only when authorized by the
screen, by one full-current-cohort confirmation. It is not a convergence test,
a biological validation, a general CPU claim, or evidence for 300 subjects.

## Frozen screen

All conditions use the first 16 subjects in the validated deterministic order,
one outer cycle, two fresh-process repeats, no warm-ups, batch size four, four
PyTorch intra-operation threads, float64 blockwise recompute, and the Engine 1.3
multi-rate schedule `momenta, momenta, template, control_points`. Only the
project/output label and `subject_batch_workers` differ.

| Batch workers | Configuration SHA-256 |
|---:|---|
| 1 | `bfc3e517dcf049aee918e2a40eeb88d00da2d3d99c40574067f30e8e2c132466` |
| 2 | `1a23ee8f250e6b9405818d857f13134e34734e5ecceffaed4aea01242165b25c` |
| 4 | `fa0f2f5892fd17ad3a65583ac4bf01ae219369a94f50c17702660aeb8f0fcabe` |

Execution order is frozen as two, four, then one worker. Each condition uses a
separate prospective optimizer design and study destination under the existing
real-data engineering root. No retry, unlisted worker count, altered thread
count, altered batch size, or extra repeat is authorized after observation.

## Bound numerical reference

The strictly verified four-thread, serial-batch Engine 1.3 screen report has
SHA-256
`7d93a0e167e8e764d8df65491592d4df2febf0f0f8a76ebd2aaea915f4c36d42`.
Both of its repeats produced:

```text
objective      -1703.242991909793
history        c461cca2ac48ee660af224e1f47e0c255d4a4ccf6456eb93285e6c1e63e2295f
template       06f93c9ecd64b407f1a69dc377d7f1ea8a6fd830df36ffc325488b988a78b2bb
control points 08e4d7ea044584405b35aadb1a3a0e13756b4cea69267664f45099c4bb8c72b6
momenta        309e3205ecc94fe553098ccedb45a88485d6d19bde24a15d594cf49daaf81ac6
```

## Screen gates and selection

Every design, study, and nested optimizer report must strictly verify. Every
repeat must contain exactly `4/4` accepted decisions, no stationary or failed
decision, finite components, and exact matches for all four hashes above.
Sampled peak RSS must not exceed `800000000` bytes.

The one-worker Engine 1.4 median is the timing control. A concurrent candidate
is eligible only if its median optimizer time is at least 10% lower. If both
qualify, select the lower median; break an exact tie in favor of fewer workers.
If neither qualifies, retain one worker and stop without a full-cohort run.

## Conditional full-cohort confirmation

Only the selected concurrent candidate, if any, may run on all 236 available
subjects for two outer cycles, one fresh process, and no warm-up. Every other
setting remains as frozen above. It must strictly verify, accept `8/8`
decisions with no stationarity or failure, and exactly match the history and
final parameter hashes from the verified Engine 1.3 236-subject reference
report SHA-256
`4d58f35b7913470650379f17e6060553692a87abc350a95f118ba426f27b6ae2`.
Its optimizer time must be no more than `3548572746120 ns` (10% below the
reference), and sampled peak RSS must not exceed `800000000` bytes.

Passing permits the worker count only for this hardware-specific engineering
path. It does not by itself change the cross-machine generated default. Failure
is retained and cannot authorize a post-hoc weaker threshold.
