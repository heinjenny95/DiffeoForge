# Engine 1.3 CPU-thread screening gate

Status: **PASS; 8 threads selected for full-cohort confirmation**

## Question

Does assigning 8 or 16 PyTorch intra-operation CPU threads materially reduce
optimizer time relative to the existing 4-thread setting on this 16-core Ryzen
9 7950X, without changing the one-cycle Engine 1.3 result?

This is a same-machine engineering screen. It is not a general CPU scaling
claim, a full-cohort timing result, a convergence test, or a production preset.

## Frozen candidates

All conditions use the same first 16 real 5k-Trochanters, float64 blockwise
recompute, subject batches of four, two Momenta visits, one outer cycle, two
fresh-process repeats, no warm-ups, and design seed `20260724`. Only the
declared CPU thread count, project label, output label, and corresponding
configuration hash differ.

| Threads | Configuration SHA-256 |
|---:|---|
| 4 | `431ee938004c3b2e0b25bb026a068e1a1fbaf1281b14e1d7a2f6ed491190e8ca` |
| 8 | `b90986aff33d4de115771edd00dad1ba321796d4924a157aab58c7ed98653d21` |
| 16 | `5512bcbbf5b1626d0eee5b7540d0eba876df79557d6134dab8be7c143f9bee9e` |

Execution order is frozen as 8, 16, then 4 threads. Each condition has its own
prospective design and study directory:

```text
engine13-thread-screen-threads08-design
engine13-thread-screen-threads08-study
engine13-thread-screen-threads16-design
engine13-thread-screen-threads16-study
engine13-thread-screen-threads04-design
engine13-thread-screen-threads04-study
```

## Gates and selection rule

Every design, study, and nested v0.2 report must strictly verify. Every repeat
must contain exactly `4/4` accepted decisions, no stationary or failed decision,
five valid history records, and finite objective components. A configuration is
not eligible if its two fresh-process final parameter/history evidence values
are inconsistent or sampled peak RSS exceeds `650000000` bytes.

The 4-thread median final objective is the numerical reference. An 8- or
16-thread candidate remains eligible only if every repeat's final objective
differs from that reference by at most `1e-9` absolute and has the same accepted
block/status schedule. Among eligible candidates, adopt a higher thread count
for a later full-cohort confirmation only if its median optimizer wall time is
at least 10% below the 4-thread median. If both qualify, select the lower median
time; break an exact tie in favor of fewer threads.

No unlisted thread count, extra repeat, warm-up, altered batch size, or post-hoc
threshold is authorized by this screen. Raw operation counts, histories,
memory, and timing remain mandatory diagnostics.

## Frozen results

All three prospective designs and completed studies verified strictly. Every
repeat accepted `4/4` decisions with no stationarity or failure. All six runs
produced exactly the same final objective `-1703.242991909793`, history SHA-256
`c461cca2ac48ee660af224e1f47e0c255d4a4ccf6456eb93285e6c1e63e2295f`,
and final template, control-point, and Momenta hashes.

| Threads | Repeat times | Median | Maximum sampled RSS | Report SHA-256 |
|---:|---:|---:|---:|---|
| 4 | 124.050 s, 130.886 s | 127.468 s | 410,918,912 B | `7d93a0e167e8e764d8df65491592d4df2febf0f0f8a76ebd2aaea915f4c36d42` |
| 8 | 103.665 s, 89.878 s | **96.772 s** | 413,085,696 B | `29061a1d1edabb27a1f0b87c13253d8a7ebec82c400a464b60c6dd5da6e5d6c4` |
| 16 | 113.539 s, 106.457 s | 109.998 s | 414,806,016 B | `4d01b62dc17167c7ea20caba87f34e281b82900f80a7303edb0b79f14b5009b2` |

Eight threads reduced median optimizer time by 24.08% relative to four. Sixteen
threads reduced it by 13.71%, but were 13.67% slower than eight, consistent
with synchronization overhead for this workload. Eight threads therefore pass
the predeclared selection rule. This supports only a separate 236-subject
confirmation on this machine; it does not justify a global default or a
general CPU scaling claim.
