# ADR 0004: Prospective multi-tile benchmark matrix

- Status: Accepted for staged implementation
- Date: 2026-07-16
- Tracking: [issue #62](https://github.com/heinjenny95/DiffeoForge/issues/62)
- Gate 1: implemented by [issue #64](https://github.com/heinjenny95/DiffeoForge/issues/64)

## Context

Benchmark design v0.1 binds one reviewed blockwise tile shape and pairs
`standard` with `recompute` at prospectively declared subject-prefix sizes. Its
runner, state, progress, and completion evidence all assume one source config
and one effective pairwise plan.

A defensible tile-size study needs several exact query/source tile shapes. A
collection of hand-edited YAML files would confound tile shape with config
identity, invite undocumented differences, complicate randomized order, and
make interruption recovery ambiguous. Reinterpreting v0.1 fields would also
weaken already frozen evidence.

## Decision

Implement the multi-tile study later as new versioned contracts. Existing
benchmark, design, and run artifacts remain readable with their original
meaning and are never migrated in place.

### Experimental factors

One matrix design will bind exactly one reviewed base modern-workflow config and
complete input inventory. It will declare three factors:

1. one or more unique deterministic subject-prefix sizes;
2. one or more unique ordered query/source tile-shape pairs; and
3. exactly the two tile-autograd strategies `standard` and `recompute`.

The design is full factorial. Each `(subject prefix, tile shape)` cell is one
pair containing both strategies. The exact condition count is therefore:

```text
subject_prefixes × tile_shapes × 2 strategies
```

No cell may be silently skipped. Duplicate shapes, transpose assumptions, zero
or negative dimensions, and an empty factor fail before publication. The CLI
must print the exact condition count before freezing and enforce a documented
upper bound to catch accidental combinatorial explosions.

### Tile plan, not multiple source configs

The matrix will not create or accept a bag of hand-edited workflow configs.
Instead, one future benchmark-protocol version may accept an explicit
benchmark-only query/source tile override. The atlas workflow, YAML,
`PairwiseEvaluationPlan`, immutable atlas-run provenance, and default behavior
remain unchanged.

Each raw benchmark report must distinguish:

- the pairwise plan declared in the hashed source config;
- the effective benchmark-only pairwise plan; and
- the tile-autograd strategy.

The operation model, largest execution tile, worker plan, review HTML, strict
schema, and semantic validator must all use the effective plan. Dense base
configs and overrides larger than the declared implementation limit fail before
a worker starts. An override is never called a workflow setting or preset.

### Pairing and order

Every cell has a stable ID containing both tile dimensions and subject-prefix
size. The matrix order algorithm is a new named/versioned SHA-256 ranking:

1. rank all `(subject prefix, tile shape)` cell IDs from the declared order
   seed; then
2. rank `standard` and `recompute` within each cell from the same seed and cell
   ID.

The complete resulting order is stored. It must not reuse the v0.1 algorithm
identifier because v0.1 pair IDs do not include tile shape. Conditions remain
adjacent within a cell so interruption state is an exact prefix and strategy
comparisons can retain their declared pairing.

### Artifact and compatibility boundary

The staged implementation requires, at minimum:

- a new benchmark report version for effective tile overrides;
- a new matrix-design version with explicit factor levels and tile-aware
  conditions;
- a compatible new study-run manifest version; and
- progress/status/verification dispatch that reads the design version rather
  than guessing from fields.

Version 0.1 design and run directories remain byte-for-byte immutable and keep
using benchmark v0.3. New writers never overwrite or upgrade them. Verifiers
must reject unknown versions rather than falling back.

The matrix design stores one immutable JSON/sidecar/HTML pre-results artifact.
The runner copies that design and the exact base config, executes each condition
into a separate raw-report directory, resumes only a verified missing suffix,
and hashes every report artifact into a strict completion manifest. Read-only
status and full verification retain the current state-ahead-of-report hard
failure rule.

### Analysis boundary

The design and runner do not calculate speedups, ratios, p-values, rankings, or
presets. Subject prefixes are nested observations, not independent cohorts;
standard and recompute share a cell; repeated fresh processes share hardware
and operating-system context. Any later analysis must model or explicitly
discuss those dependencies and its prospectively chosen outcomes.

Sampled process RSS remains a 5 ms observation that can miss short peaks. A
tile allocation bound, saved-tensor graph observation, or lower sampled RSS is
not by itself peak-memory evidence. Objective/gradient timing is not full-atlas
runtime. Matrix completion is not a 300-subject feasibility verdict.

## Staged implementation gates

1. ~~Add and test the benchmark-only effective tile override and its new strict
   report, including real fresh-process Windows/Ubuntu smoke coverage.~~
   Implemented as raw benchmark report v0.4; representative measurements are
   not part of this gate.
2. Add matrix design collection, semantic reconstruction, immutable
   publication, and condition-count review; do not execute it yet.
3. Extend execution, progress, status, completion, and full verification with
   interruption/reconciliation tests while retaining v0.1 fixtures.
4. Freeze a real representative design before collecting results.
5. Define a separate prospective analysis plan before calculating comparisons.
6. Consider a public preset only after representative full-workflow evidence.

Each gate is a separate reviewable change. A later gate may not weaken an
earlier artifact's validator or scientific boundary.

## Consequences

The implementation requires additional schemas and explicit version dispatch,
but gains one controlled source config, auditable factor identity, deterministic
paired order, safe resume semantics, and clean backward compatibility. Users
will not need to hand-maintain a collection of nearly identical YAML files.
