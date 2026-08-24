# Engine 1.3 full-cohort efficiency gate

Status: **frozen before the two-cycle result exists**

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
