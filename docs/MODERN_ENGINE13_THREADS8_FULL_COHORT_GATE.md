# Engine 1.3 eight-thread full-cohort confirmation

Status: **frozen before the confirmation result exists**

## Question

Does the eight-thread setting selected by the frozen 16-subject CPU screen
preserve the exact Engine 1.3 result and reduce optimizer time by at least 10%
on all 236 available real 5k-Trochanters?

This is a same-machine adoption gate for one runtime setting. It is not a
general CPU scaling result, a convergence test, a biological validation, or a
claim about 300 subjects.

## Frozen candidate

- candidate configuration SHA-256:
  `b90986aff33d4de115771edd00dad1ba321796d4924a157aab58c7ed98653d21`;
- Modern engine implementation: `1.3`;
- optimizer benchmark artifact version: `0.2`;
- CPU threads: `8`; subject batch size: `4`;
- deterministic subject-prefix size: `236` of `236` available subjects;
- outer-cycle cap: `2`;
- schedule: `momenta`, `momenta`, `template`, `control_points`;
- repeats: `1`; warm-ups: `0`; design order seed: `20260725`;
- no automatic retry or alternate thread, batch, or cycle count.

Declared destinations:

```text
engine13-threads8-full-cohort-confirmation-design
engine13-threads8-full-cohort-confirmation-study
```

## Bound four-thread reference and gates

The strictly verified four-thread Engine 1.3 report SHA-256 is
`4d58f35b7913470650379f17e6060553692a87abc350a95f118ba426f27b6ae2`.
It used `3942858606800 ns` optimizer time and produced:

```text
history        f53b03b5344e681fc84b7654e7d8a2d8a14d4548a32d46997f847316969dbf13
template       61e454baf711d0ef3cb1525e4f9b2774af603f08b7880cce333a4154ac9284b3
control points 9a16a724bb36d89fb88d6aa5c0e409dcba32c022b3d78992bb0cbb099de90e01
momenta        2778580135caf698332c2c3f20ebaab7b185c52abfea7a6650b6c9857f0ee28d
```

The candidate passes only if all conditions hold:

1. design, study, and nested v0.2 report strictly verify;
2. exactly `8/8` decisions are accepted with no stationary or failed decision;
3. all nine history records and all four hashes above match exactly;
4. objective, attachment, regularity, counters, and termination match the
   four-thread reference exactly;
5. optimizer wall time is at most `3548572746120 ns`, 90% of the reference;
6. sampled peak RSS is at most `650000000` bytes.

Failure is retained and does not authorize a post-hoc retry. Passing permits
eight threads only as a hardware-specific candidate for subsequent development;
it does not change the generated cross-machine default by itself.
