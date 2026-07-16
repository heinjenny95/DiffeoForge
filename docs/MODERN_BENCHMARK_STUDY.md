# Prospective paired benchmark designs

Status: **implemented pre-results design; execution and analysis remain separate**

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
than an absolute local path. A future execution service must receive the source
config, verify its digest and input inventory against the frozen design, and
only then replace that placeholder. The design itself therefore does not
silently depend on one researcher's directory layout.

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

Design v0.1 binds one reviewed blockwise tile shape. It does not yet orchestrate
execution, resume interrupted studies, compare multiple tile configurations,
pool reports, calculate speedups, test significance, rank strategies, or select
a public preset. Each eventual condition must keep its raw benchmark v0.3
report. A multi-size study needs a separately versioned cross-configuration
design rather than an informal collection of hand-edited YAML files.

Before executing a paper study, archive the immutable design and its integrity
sidecar in version control or another timestamped record. An implementation
smoke test, a completed design, or one favorable raw report is not evidence of
lower peak RAM, faster complete atlas construction, or feasibility for 300
subjects.
