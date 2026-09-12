# Guarded Modern complete-cycle recovery

Status: **implemented source-level safety path; not automatic and not yet exposed in the GUI**

## Purpose

A hard process or machine failure can leave a private unpublished Modern run
whose process lease is no longer held. New Modern workflows store immutable
state after every fully completed optimizer cycle. Recovery creates a separate,
prospective successor from the latest such state without modifying, publishing,
or deleting the abandoned directory.

First inspect the exact intended destination:

```powershell
diffeoforge modern-private-status "C:\path\to\intended-run" --json
```

Only a candidate classified as `abandoned` is eligible. An `active`,
`unattributed`, `invalid_metadata`, `indeterminate`, or `unsafe_link` candidate
fails closed.

Freeze and verify a plan without starting the optimizer:

```powershell
diffeoforge modern-checkpoint-recovery-init `
  "C:\path\to\.intended-run.tmp-0123456789abcdef0123456789abcdef" `
  --output "C:\path\to\intended-run-recovery"

diffeoforge modern-checkpoint-recovery-verify `
  "C:\path\to\intended-run-recovery"
```

By default, the successor receives the number of cycles that remained under
the abandoned run's original cap. `--cycles N` makes a different new cap
explicit; zero is valid and publishes the recovered committed state through a
normal verified bundle without another optimizer cycle. `--threads N` may only
repeat the parent thread count. Exact continuation fails closed if it differs.

The plan contains a marked v0.5 YAML but does not authorize or launch compute:

```powershell
diffeoforge modern-run `
  "C:\path\to\intended-run-recovery\modern-checkpoint-recovery.yaml"

diffeoforge modern-checkpoint-recovery-verify-run `
  "C:\path\to\intended-run-recovery" `
  "C:\path\to\intended-run-recovery-modern-run"
```

The completed-run verifier requires the exact frozen source-config hash, Modern
engine implementation revision, CPU/float64 runtime and thread count, model and
optimizer settings, subject identity/order, and a recomputed initial objective
equal to the checkpoint objective within the declared floating-point tolerance.

## Frozen evidence

The recovery directory embeds:

- the complete checkpoint manifest, sidecar, template, control points, and
  momenta;
- the original source and effective configuration;
- the original effective template input and every subject input;
- a complete byte-size/SHA-256 inventory;
- the derived successor configuration and an offline HTML review page.

Verification is self-contained after creation and does not trust the abandoned
directory to remain available.

## Scientific and operational boundary

Recovery never overwrites the abandoned directory or its intended destination.
It does not recover partial-cycle parameter updates, a candidate line-search
state, an autograd graph, process memory, wall-clock history, or an exact
mid-instruction continuation. It also does not establish convergence,
biological validity, optimizer equivalence, or production suitability. The
abandoned directory remains private evidence and requires a separate retention
or cleanup decision outside this command.
