# Engine 1.3 eight-thread full-cohort confirmation

Status: **FAIL; exact-result and 10%-time gates failed without a retry**

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

## Frozen result

The prospective design, completed study, and nested benchmark v0.2 report
verified strictly. The raw report SHA-256 is
`4b6938ac8302e085914a5665609cdd7c973aadf34318f8ad3e821bed8866a026`.

| Frozen gate | Required | Observed | Result |
|---|---:|---:|---|
| Strict design/study/report verification | pass | pass | PASS |
| Accepted decisions | `8/8` | `8/8` | PASS |
| Stationary / failed decisions | `0 / 0` | `0 / 0` | PASS |
| Exact history and parameter hashes | match | differ | **FAIL** |
| Exact objective/components | match | last-bit differences | **FAIL** |
| Optimizer wall time | at most `3548572746120 ns` | `3737386864000 ns` | **FAIL** |
| Sampled peak RSS | at most `650000000 B` | `545009664 B` | PASS |

The eight-thread run used 62.290 minutes, only 5.21% less than the four-thread
reference and 188,814,117,880 ns above the predeclared threshold. Work counts
and termination matched exactly: 41 objective evaluations, 16 gradient
evaluations, eight accepted-candidate gradients, 17 line-search evaluations,
nine deferred rejected-candidate gradients, and the two-cycle cap.

The numerical differences were tiny but nonzero. Final objective differed by
`-1.8189894035458565e-12`, final regularity by
`7.105427357601002e-14`, and accepted history objectives differed by at most
`1.0913936421275139e-11`. Final attachment matched as a float. These reduction-
order effects changed the complete history and all final parameter hashes, so
the exact-result gate correctly rejected the candidate.

Eight threads are not adopted. The 16-subject speedup did not transfer
materially to the serial 236-subject batch loop. The next optimization must
explicitly restructure cohort execution or introduce a separately validated
GPU path rather than raising the global thread default.
