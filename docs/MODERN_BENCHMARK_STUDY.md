# Prospective paired benchmark designs

Status: **implemented pre-results design and resumable execution; analysis remains separate**

`modern-benchmark-design` freezes how configured blockwise `standard` and
`recompute` objective/gradient observations are to be collected before any of
those observations exist. This makes the chosen subset sizes, repeat count, and
condition order auditable and harder to adjust after seeing a favorable result.

It is a design tool, not a benchmark runner or statistical-analysis tool.

## Create a design

Start from one reviewed blockwise modern-workflow configuration with Procrustes
disabled:

```powershell
diffeoforge modern-benchmark-design modern-atlas.yaml `
  --subjects 5 20 50 `
  --repeats 7 `
  --warmups 1 `
  --order-seed 20260716 `
  --output modern-atlas.benchmark-study
```

The subject values are unique deterministic prefixes of the same validated
mesh-path order used by `modern-run` and `modern-benchmark`. Every requested
prefix becomes one pair containing exactly one `standard` and one `recompute`
condition. Both conditions use the same config, selected subject prefix,
warm-up count, and repeat count.

Dense configurations fail because dense execution has no tiles to recompute.
Procrustes-enabled configurations fail because the objective benchmark does not
measure the preprocessing pipeline.

## Immutable pre-results artifact

The new directory contains exactly:

```text
modern-atlas.benchmark-study/
  study-design.json
  study-design.sha256
  study-design.html
```

The directory is never overwritten. The JSON follows
`modern-benchmark-design-v0.1.json`; the sidecar covers its exact bytes. The
verifier also regenerates the review HTML from the JSON and requires an exact
match.

The design binds:

- DiffeoForge and objective-benchmark protocol versions;
- source-config filename, project label, and SHA-256;
- template and complete available subject inventory with labels, bytes,
  geometry counts, and SHA-256 values;
- model, first gradient block, CPU-thread count, random seed, and configured
  blockwise tile shape;
- requested subject-prefix sizes, repeats, warm-ups, order seed, and the exact
  condition sequence;
- a unique pair ID, separate output directory, and argument vector for every
  condition; and
- the analysis policy and scientific boundary that existed before results.

The argument vectors deliberately contain `<verified-source-config>` rather
than an absolute local path. The execution service receives the source config,
verifies its digest and input inventory against the frozen design, and only
then replaces that placeholder. The design itself therefore does not silently
depend on one researcher's directory layout.

## Versioned condition order

Version 0.1 ranks pair labels and the two strategies within each pair by
SHA-256 of the declared algorithm identifier, seed, and label. The complete
resulting order is stored, so reproduction does not depend on a future Python
random-number implementation.

This deterministic permutation makes order explicit; it does not by itself
eliminate thermal, background-load, cache, hardware, or temporal confounding.
Those factors still require a controlled experimental environment and a
prospectively justified analysis.

## Deliberate scope boundaries

Design v0.1 binds one reviewed blockwise tile shape. Its runner executes and
resumes that one frozen sequence, but does not compare multiple tile
configurations, pool reports, calculate speedups, test significance, rank
strategies, or select a public preset. Each condition keeps its raw benchmark
v0.3 report. A multi-size study needs a separately versioned
cross-configuration design rather than an informal collection of hand-edited
YAML files.

Before executing a paper study, archive the immutable design and its integrity
sidecar in version control or another timestamped record. An implementation
smoke test, a completed design, or one favorable raw report is not evidence of
lower peak RAM, faster complete atlas construction, or feasibility for 300
subjects.

## Execute or resume the frozen design

After archiving and reviewing the design, run exactly its stored sequence:

```powershell
diffeoforge modern-benchmark-study `
  modern-atlas.benchmark-study `
  modern-atlas.yaml `
  --output modern-atlas.benchmark-study.run
```

Before creating or resuming any report, the runner:

1. verifies the external design JSON, sidecar, and regenerated HTML;
2. regenerates the design from the supplied source config and complete current
   input inventory and requires exact equality, including software and protocol
   versions;
3. verifies the copied source-config bytes and frozen design inside an existing
   run;
4. rejects a concurrent live process using a process-identity lock; and
5. verifies that existing condition reports form a valid prefix of the frozen
   order.

Each missing condition invokes `modern-benchmark` v0.3 with the exact stored
subject count, repeats, warm-ups, strategy, and separate output directory. A
condition counts as complete only when its strict JSON passes schema and
semantic checks, its CSV rows exactly match that JSON, and its HTML exactly
matches a fresh rendering from the JSON.

If execution is interrupted, the atomic state remains `interrupted` or
`running`. A later invocation revalidates every existing raw report and resumes
only the missing suffix. A valid report written just before a hard interruption
is reconciled into state and the event log; it is not recomputed or
overwritten.

## Completed run evidence

A completed run contains the immutable design copy, exact source-config copy,
atomic state, append-only lifecycle events, one directory per condition, and:

```text
study-run.json
study-run.sha256
```

The strict v0.1 completion manifest binds every condition's sequence, pair,
subject count, strategy, report directory, and SHA-256 values for
`benchmark.json`, `samples.csv`, and `benchmark.html`. Verification reconstructs
those records from disk and requires the state and completed-event order to
match the frozen design.

The completion manifest explicitly records `analysis_performed: false`. The
runner does not pool repeats, subtract timings, compute ratios or p-values,
rank conditions, or change a workflow setting. Analysis remains a later,
separately versioned evidence stage after a real prospectively frozen study is
collected under controlled conditions.

## Read-only inspection and verification

Status inspection never resumes, reconciles, deletes, or writes:

```powershell
diffeoforge modern-benchmark-study-status `
  modern-atlas.benchmark-study.run

diffeoforge modern-benchmark-study-status `
  modern-atlas.benchmark-study.run --json
```

It strictly verifies the copied design and source-config digest, every existing
raw-report prefix, state prefix, event sequence, manifest presence, and lock
owner. The machine-readable output distinguishes state-recorded completions
from verified reports and names the next frozen condition.

If a hard interruption happened after a report was atomically published but
before state was updated, status reports `reconciliation_required: true`; the
runner may safely promote that already verified report. The inverse is not
recoverable: if state claims a completed condition whose report is absent, both
status and runner fail. Recomputing it silently would erase evidence of loss or
tampering.

For a completed or copied study, run the dedicated full verifier:

```powershell
diffeoforge modern-benchmark-study-verify `
  modern-atlas.benchmark-study.run
```

Successful verification means the frozen identities, separate reports,
condition order, state, events, manifest, and hashes agree. It still does not
mean either strategy is faster, uses less peak memory, or is ready as a public
default.
