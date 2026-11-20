# Engine 1.3 multi-rate efficiency gate

Status: **PASS; frozen gate evaluated without a retry**

## Question

Can two consecutive Momenta updates per outer cycle reach at least the
ten-cycle Engine 1.1 Steepest objective in less measured optimizer time on the
same deterministic 16-subject real 5k-Trochanter prefix?

This is one integrated engineering-candidate gate. It does not isolate every
code and optimizer difference, prove convergence, validate biology, or support
a general performance claim.

## Frozen candidate

- candidate configuration SHA-256:
  `431ee938004c3b2e0b25bb026a068e1a1fbaf1281b14e1d7a2f6ed491190e8ca`;
- Modern engine implementation: `1.3`;
- optimizer benchmark artifact version: `0.2`;
- deterministic subject-prefix size: `16`;
- benchmark-only outer-cycle cap: `5`;
- block schedule per cycle: `momenta`, `momenta`, `template`, `control_points`;
- maximum committed decisions: `20`;
- repeats: `1`; warm-ups: `0`; design order seed: `20260722`;
- no automatic retry, alternate repetition count, or alternate cycle cap after
  observing the result.

Declared destinations:

```text
engine13-prospective-16-subject-5-cycle-momenta2-v02-design
engine13-prospective-16-subject-5-cycle-momenta2-v02-study
```

The generated prospective design must strictly verify before execution. Its
hashed inventory and copied configuration are authoritative.

## Bound baseline and gates

The strictly verified Engine 1.1 16-subject/10-cycle Steepest report has
SHA-256 `a045d29606acaebe2430bb77d17eb09c766b0235d97498a44cdca54e65532eef`.
The candidate passes only if all conditions hold:

1. the study and nested v0.2 report strictly verify;
2. exactly `20/20` decisions are accepted, with no stationary or failed
   decision and `failed_block == null`;
3. all 21 history records are finite, ordered, counter-consistent, and
   hash-consistent;
4. `final_objective >= -296.6588473308086`;
5. `optimizer_wall_time_ns <= 753033437900`;
6. sampled peak RSS does not exceed `460000000` bytes.

Attachment and regularity components, exact objective/gradient/line-search
work, per-block gains, and the complete trajectory remain mandatory
diagnostics. Passing supports only this frozen same-machine condition. Failure
is retained and does not authorize post-hoc gates.

## Frozen result

The prospective design verified before execution. The completed study and its
nested optimizer benchmark v0.2 report then verified strictly. The raw report
SHA-256 is
`bb5820bcb118b24e262b16517024e72cee63274959a5df2192f95ec69d4f56b5`;
its 21-record decision history SHA-256 is
`1ae625ea6a837361edb3c5e3b796f8d01ac55b2b6aeedcdd64fdf9d8267c365b`.

| Frozen gate | Required | Observed | Result |
|---|---:|---:|---|
| Strict study/report verification | pass | pass | PASS |
| Accepted decisions | `20/20` | `20/20` | PASS |
| Stationary / failed decisions | `0 / 0` | `0 / 0` | PASS |
| Valid history records | `21` | `21` | PASS |
| Final objective | at least `-296.6588473308086` | `-160.39978136827878` | PASS |
| Optimizer wall time | at most `753033437900 ns` | `542635424200 ns` | PASS |
| Sampled peak RSS | at most `460000000 B` | `413716480 B` | PASS |

The candidate used 9.044 minutes of measured optimizer time, 27.94% less than
the bound Engine 1.1 baseline, while improving the objective by 136.259. Its
final components were attachment `-150.15853400454972` and regularity
`-10.241247363729071`. It performed 90 objective evaluations, 40 gradient
evaluations, 20 accepted-candidate gradient evaluations, and 30 line-search
evaluations. No block failed and termination was the declared five-cycle cap,
not convergence.

Cycle-end objectives were:

```text
cycle 1  -1703.242991909793
cycle 2   -850.4559491057385
cycle 3   -565.2663526177593
cycle 4   -342.18833602916493
cycle 5   -160.39978136827878
```

Summed accepted objective gains were `5301.35476190824` for Momenta,
`229.3176190160629` for template vertices, and `265.5515491103099` for control
points. This supports multi-rate scheduling for this exact engineering
condition. It does not establish convergence, a universal schedule, biological
validity, or 236/300-subject production feasibility.
