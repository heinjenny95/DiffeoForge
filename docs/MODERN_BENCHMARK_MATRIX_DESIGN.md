# Prospective multi-tile benchmark matrix design

This protocol freezes a full-factorial benchmark plan before results exist. It
solves the reproducibility problem of comparing several tile shapes without
maintaining nearly identical YAML files. Creating the design inspects and hashes
inputs, but performs no objective evaluation, timing, memory sampling, ranking,
or recommendation.

## Create the pre-results artifact

Start from one reviewed modern-workflow config whose pairwise mode is
`blockwise` and whose Procrustes preprocessing is disabled:

```powershell
diffeoforge modern-benchmark-matrix-design modern-atlas.yaml `
  --subjects 5 20 50 `
  --tile-shape 64x64 `
  --tile-shape 128x256 `
  --repeats 7 `
  --warmups 1 `
  --order-seed 20260717
```

The default output is `modern-atlas.benchmark-matrix`. The CLI first prints the
exact number of cells and conditions against the 1000-condition ceiling, then
atomically publishes exactly three files:

- `matrix-design.json`, the strict machine-readable contract;
- `matrix-design.sha256`, binding the JSON bytes; and
- `matrix-design.html`, a regenerated human-review view.

An existing destination is never replaced. The verifier rejects missing or
extra files, a sidecar mismatch, non-schema data, a semantically altered
schedule, or HTML that differs from deterministic regeneration.

Run the read-only verifier after copying or archiving a design:

```powershell
diffeoforge modern-benchmark-matrix-design-verify `
  modern-atlas.benchmark-matrix
```

## Factors and exact condition count

The factors are one or more unique subject-prefix sizes, one or more unique
ordered query/source tile pairs, and exactly `standard` plus `recompute`. The
complete factorial is mandatory:

```text
cells = subject prefixes × ordered tile shapes
conditions = cells × 2 strategies
```

`--tile-shape 64x128` means 64 query rows and 128 source rows. The transposed
`128x64` level is different and may appear in the same design; repeating
`64x128` is invalid. Dimensions must be positive and no larger than 999999 so
their stable six-digit ID fields remain unambiguous. This is an artifact-format
limit, not a measured safe tile range.

The condition ceiling is a guard against accidentally publishing a huge
factorial. It is not a runtime estimate. Subject-prefix sizes remain limited to
`1..100000` and cannot exceed the complete frozen input inventory.

## Identity, pairing, and deterministic order

Every cell ID includes the subject count and both ordered tile dimensions, for
example:

```text
subjects-000020-tiles-q000128-s000256
```

The versioned algorithm
`sha256-ranked-subject-tile-cells-and-within-cell-strategies-v0.1` ranks all
stable cell IDs from the declared seed. It then ranks the two strategies within a cell;
those two conditions stay adjacent. The entire resulting order and exact argv
are stored. Semantic verification reconstructs them rather than merely trusting
the JSON fields.

Each argv includes both benchmark-only tile overrides. Therefore any later
executor must create raw benchmark report v0.4, which separately records the
hashed source-config plan and the effective condition plan. The source YAML,
public `PairwiseEvaluationPlan`, atlas optimizer, reconstruction, and PCA remain
unchanged.

## Compatibility and scientific boundary

This is a separate command, Python module, schema, and artifact family. The
existing `modern-benchmark-design` v0.1 and `modern-benchmark-study` service
retain their single-source-tile benchmark v0.3 meaning. The current study runner
cannot consume a matrix design. A later execution gate must introduce explicit
versioned dispatch, progress, interruption recovery, completion evidence, and
full verification.

The artifact does not establish that one tile shape or strategy is faster, uses
less peak memory, is a safe preset, or makes a 300-subject atlas feasible.
Subject prefixes are nested, strategy observations are paired within cells, and
sampled process RSS is not guaranteed peak memory. Analysis and public defaults
remain separate prospective decisions under
[ADR 0004](decisions/0004-prospective-multi-tile-matrix.md).
