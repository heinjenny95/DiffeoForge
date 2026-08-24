# Engine 1.2 shorter-cycle L-BFGS gate

Status: **frozen before the seven-cycle result exists**

## Question

Can the integrated Engine 1.2 multi-block L-BFGS configuration reach at least
the ten-cycle Engine 1.1 Steepest objective in less measured optimizer time on
the same deterministic 16-subject real 5k-Trochanter prefix?

This is an engineering efficiency gate for one machine, cohort prefix, and
configuration. It is not an isolated causal comparison of direction formulas,
a convergence claim, a biological validation, or a general runtime claim.

## Frozen inputs and scope

- candidate source configuration SHA-256:
  `f4c93ba2fa1ce63bb42ecd1951edf6d18f136010b202c5c81d975434f335b5eb`;
- Modern engine implementation: `1.2`;
- optimizer benchmark artifact version: `0.2`;
- deterministic subject-prefix size: `16`;
- benchmark-only cycle cap: `7`;
- measured repeats: `1`;
- warm-up runs: `0`;
- design order seed: `20260722`;
- block order: `momenta`, `template`, `control_points`;
- no automatic retry or alternate cycle cap after observing the result.

The prospective design and study destinations are declared as:

```text
engine12-prospective-16-subject-7-cycle-lbfgs-v02-design
engine12-prospective-16-subject-7-cycle-lbfgs-v02-study
```

The generated design must strictly verify before the study starts. Its hashed
inventory and copied configuration are authoritative if a human-readable path
or filename differs from this note.

## Bound baseline

The baseline is the completed and strictly verified Engine 1.1
16-subject/10-cycle Steepest report with SHA-256
`a045d29606acaebe2430bb77d17eb09c766b0235d97498a44cdca54e65532eef`.
Its pre-observed thresholds are:

- final objective: `-296.6588473308086`;
- optimizer wall time: `753033437900 ns`;
- failed decisions: `0`;
- failed block: `null`.

The completed 10-cycle Engine 1.2 L-BFGS context report has SHA-256
`fce506a4aa520db0ae875cf12a00a726e1117020f57bd0d5f0a6e9f41e6ef578`.
It motivated the shorter cap but does not set or replace the baseline gates.

## Predeclared gate

The seven-cycle candidate passes only if all of the following hold:

1. the completed study and nested report strictly verify;
2. `failed_decisions == 0` and `failed_block == null`;
3. termination is a declared normal cap or convergence termination;
4. every stored v0.2 history record is finite and verifier-consistent;
5. `final_objective >= -296.6588473308086`;
6. `optimizer_wall_time_ns <= 753033437900`.

Passing supports only the statement that this one integrated candidate reached
the baseline objective threshold within the baseline time threshold under the
frozen conditions. Failure is retained as evidence and does not authorize a
post-hoc threshold, retry, or winner claim.

Attachment, regularity, sampled RSS, exact work counters, and the per-decision
trajectory remain mandatory diagnostics even when the binary gate passes.
