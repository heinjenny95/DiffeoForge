# Engine 1.3 multi-rate efficiency gate

Status: **frozen before the five-cycle result exists**

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
