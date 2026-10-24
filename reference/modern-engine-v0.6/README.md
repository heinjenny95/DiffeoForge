# Modern Engine v0.6 prospective multi-tile study

This directory archives a pre-results full-factorial engineering design for
the openly licensed CC0 synthetic meshes. It crosses subject prefixes 1, 3,
and 5 with ordered query/source tile shapes 32 by 32, 64 by 64, and 128 by 128.
Every cell contains paired `standard` and `recompute` autograd conditions.

The design freezes nine cells and eighteen conditions, five measured
fresh-process repeats plus one warm-up per condition, and deterministic order
seed 20260722. It was strictly verified before any condition was executed.
The JSON and deterministic HTML contain no measurement, comparison, ranking,
or preset recommendation.

At the commit that first archives this directory, no raw report existed. Any
later run must remain separate and preserve all condition reports. The tiny
synthetic surfaces are useful for orchestration and integrity evidence, not
representative full-atlas or large-cohort performance.

Verify without executing a benchmark:

```powershell
diffeoforge modern-benchmark-matrix-design-verify `
  reference/modern-engine-v0.6/multi-tile-design
```

## Completed raw execution

After the design had been archived in commit `81551d4`, all eighteen frozen
conditions were executed into `multi-tile-run`. Each condition contains five
measured fresh-process observations plus one warm-up. All eighteen v0.4
JSON/CSV/HTML report triplets, atomic state, lifecycle events, and the final
v0.2 run manifest pass strict verification. Re-opening the completed run left
all 62 files byte-identical.

The completion manifest records `analysis_performed: false`. This is raw
engineering evidence on tiny synthetic geometry. It makes no claim about a
faster strategy, a lower-memory tile shape, statistical significance,
full-atlas runtime, convergence, a safe public preset, or target-cohort
feasibility.

Verify the completed run without modifying it:

```powershell
diffeoforge modern-benchmark-matrix-study-verify `
  reference/modern-engine-v0.6/multi-tile-run
```
