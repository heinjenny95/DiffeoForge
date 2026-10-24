# Engine 1.3 full-cohort efficiency gate

Status: **FAIL; time gate failed without a retry**

## Question

Can the Engine 1.3 multi-rate schedule reach at least the three-cycle Engine
1.1 Steepest objective with less measured optimizer time on all 236 available
real 5k-Trochanters?

This is one same-machine engineering gate. It tests the present cohort, mesh
resolution, parameterization, and deterministic run order. It does not prove
convergence, biological validity, 300-subject behavior, or a general speedup.

## Frozen candidate

- candidate configuration SHA-256:
  `431ee938004c3b2e0b25bb026a068e1a1fbaf1281b14e1d7a2f6ed491190e8ca`;
- Modern engine implementation: `1.3`;
- optimizer benchmark artifact version: `0.2`;
- deterministic subject-prefix size: `236` of `236` available subjects;
- benchmark-only outer-cycle cap: `2`;
- block schedule per cycle: `momenta`, `momenta`, `template`, `control_points`;
- maximum committed decisions: `8`;
- repeats: `1`; warm-ups: `0`; design order seed: `20260723`;
- no automatic retry, alternate repetition count, or alternate cycle cap after
  observing the result.

Declared destinations:

```text
engine13-prospective-236-subject-2-cycle-momenta2-v02-design
engine13-prospective-236-subject-2-cycle-momenta2-v02-study
```

The prospective design must strictly verify before execution. Its hashed input
inventory and copied configuration are authoritative.

## Bound baseline and gates

The strictly verified Engine 1.1 236-subject/three-cycle Steepest report has
SHA-256 `677ddc16d774a4a34f731928e1efe81d2d3043ebac68b6e3be3990069a8a165d`.
It accepted `9/9` decisions, reached objective `-12489.3205917409` in
`2918383671900 ns`, and used `530972672` bytes sampled peak RSS.

The candidate passes only if all conditions hold:

1. the prospective design, completed study, and nested v0.2 report strictly
   verify;
2. exactly `8/8` decisions are accepted, with no stationary or failed decision
   and `failed_block == null`;
3. all nine history records are finite, ordered, counter-consistent, and
   hash-consistent;
4. `final_objective >= -12489.3205917409`;
5. `optimizer_wall_time_ns <= 2918383671900`;
6. sampled peak RSS does not exceed `600000000` bytes.

Attachment and regularity components, exact objective/gradient/line-search
work, cycle ends, per-block gains, and the complete trajectory remain mandatory
diagnostics. Passing supports only this frozen full-current-cohort condition.
Failure is retained and does not authorize a post-hoc retry or weaker gate.

## Frozen result

The prospective design verified before execution. The completed study and its
nested optimizer benchmark v0.2 report then verified strictly. The raw report
SHA-256 is
`4d58f35b7913470650379f17e6060553692a87abc350a95f118ba426f27b6ae2`;
its nine-record history SHA-256 is
`f53b03b5344e681fc84b7654e7d8a2d8a14d4548a32d46997f847316969dbf13`.

| Frozen gate | Required | Observed | Result |
|---|---:|---:|---|
| Strict design/study/report verification | pass | pass | PASS |
| Accepted decisions | `8/8` | `8/8` | PASS |
| Stationary / failed decisions | `0 / 0` | `0 / 0` | PASS |
| Valid history records | `9` | `9` | PASS |
| Final objective | at least `-12489.3205917409` | `-8545.854488271007` | PASS |
| Optimizer wall time | at most `2918383671900 ns` | `3942858606800 ns` | **FAIL** |
| Sampled peak RSS | at most `600000000 B` | `542019584 B` | PASS |

The candidate used 65.714 minutes of measured optimizer time, 35.10% more than
the bound Engine 1.1 baseline. It improved the objective by 3943.466 and
reduced its magnitude by 31.57%. Its final components were attachment
`-8461.70938769846` and regularity `-84.1451005725466`. It performed 41
objective evaluations, 16 gradient evaluations, eight accepted-candidate
gradient evaluations, and 17 line-search evaluations. Nine rejected
line-search candidates required no gradient. No block failed and termination
was the declared two-cycle cap, not convergence.

Cycle-end objectives were:

```text
cycle 1  -21465.513727650712
cycle 2   -8545.854488271007
```

The first record exceeding the baseline quality threshold was decision six,
the second consecutive Momenta visit in cycle two, at objective
`-9519.941841703901`. Summed accepted objective gains were
`76953.34965745053` for Momenta, `2768.683257517847` for template vertices,
and `2984.4476057149404` for control points.

The result supports the mathematical value of the multi-rate schedule on the
full current cohort, but rejects this serial execution as an efficiency win.
Because every block still evaluates all 236 subjects, full-cohort evaluation
cost dominates the saved outer decisions. The next optimization must target
cohort execution rather than weaken this gate or rerun a post-hoc cycle cap.
