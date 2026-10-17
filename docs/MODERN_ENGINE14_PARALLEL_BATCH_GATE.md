# Engine 1.4 parallel-subject-batch gate

Status: **PASS; two workers passed the full-cohort confirmation**

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

## Frozen screen result

All three designs, completed studies, and six nested v0.2 benchmark samples
strictly verified. Every repeat accepted `4/4` decisions with no stationarity
or failure. All six repeats exactly matched the bound history, template,
control-point, and Momenta hashes and final objective.

| Workers | Repeat times | Median | Maximum sampled RSS | Report SHA-256 | Gate |
|---:|---:|---:|---:|---|---|
| 1 | 157.715 s, 152.270 s | 154.993 s | 396,738,560 B | `eb5647d955e83b459243925e3d03b0722d44d3e6124fb17fd73cde88ac390a2b` | control |
| 2 | 117.527 s, 118.772 s | **118.150 s** | 585,330,688 B | `686e5af543760beaf3e6540484d593a18a73d8c77500c20527d25c3e1186860b` | **PASS** |
| 4 | 134.104 s, 136.506 s | 135.305 s | 836,759,552 B | `47964b153e7e785d170ef71819810815dddbacce6d6ed13a008bc3f1c5346637` | FAIL memory |

Two workers reduced median optimizer time by 23.77% relative to the frozen
one-worker control and remained below the memory ceiling. Four workers were
12.70% faster than control but slower than two workers and exceeded the memory
ceiling in both repeats. The predeclared rule therefore selects two workers for
the one authorized full-cohort confirmation.

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

The selected prospective design was frozen before execution at:

```text
engine14-parallel-batches-workers02-full-cohort-design
engine14-parallel-batches-workers02-full-cohort-study
```

Its strictly verified `optimizer-design.json` SHA-256 is
`b0d33f3d2c75be30bcfe6eec7f0a530677dbab4c6876a6c1e05cddf56a87a6c4`.
It binds Engine `1.4`, two workers, 236 subjects, two cycles, one repeat, zero
warm-ups, and order seed `20260727`; it contains no result.

## Frozen full-cohort result

The completed study and nested optimizer benchmark v0.2 report strictly
verified. The raw report SHA-256 is
`5431ec8dd42313ff22d92238ab9a4d6f0845f490ee2f633e85305fe07db95b29`.

| Frozen gate | Required | Observed | Result |
|---|---:|---:|---|
| Strict design/study/report verification | pass | pass | PASS |
| Accepted decisions | `8/8` | `8/8` | PASS |
| Stationary / failed decisions | `0 / 0` | `0 / 0` | PASS |
| Exact history and parameter hashes | match | exact match | PASS |
| Exact objective/components | match | exact match | PASS |
| Optimizer wall time | at most `3548572746120 ns` | `3093296929000 ns` | PASS |
| Sampled peak RSS | at most `800000000 B` | `780652544 B` | PASS |

The two-worker candidate used 51.555 minutes, 21.55% less than the bound
65.714-minute serial reference. It retained the exact history SHA-256
`f53b03b5344e681fc84b7654e7d8a2d8a14d4548a32d46997f847316969dbf13`
and exact template, control-point, and Momenta hashes. Its final objective
`-8545.854488271007` and both components matched exactly. Work also matched:
41 objective evaluations, 16 gradient evaluations, eight accepted-candidate
gradients, and 17 line-search evaluations. No block failed; termination was the
declared two-cycle cap, not convergence.

The candidate passed the time ceiling by 455.276 seconds. Memory had only
19,347,456 bytes of headroom, so this result supports two workers for this
128-GB Ryzen 9 7950X engineering workload but does not support four workers or
a cross-machine default change.

Passing permits the worker count only for this hardware-specific engineering
path. It does not by itself change the cross-machine generated default.
