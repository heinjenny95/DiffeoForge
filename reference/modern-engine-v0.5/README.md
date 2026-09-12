# Modern Engine v0.5 prospective paired study

This directory archives the pre-results design for a public, openly licensed
engineering study of blockwise `standard` versus `recompute` autograd. The
design was created from `examples/minimal-modern-atlas-blockwise.yaml` and the
CC0 synthetic meshes.

The design freezes subject prefixes 1, 3, and 5; five fresh-process repeats per
condition; one warm-up evaluation per repeat; 64 by 64 tiles; and deterministic
order seed 20260722. Its six conditions contain no measurements, comparisons,
or rankings. `study-design.sha256` binds the exact JSON bytes; the HTML is a
deterministic review rendering.

At the commit that first archives this directory, no condition had been run.
The later execution directory, if committed, must remain separate and retain
all raw reports. A completed run is still only an objective-plus-gradient
engineering observation on a tiny synthetic dataset, not a full atlas runtime,
scientific validation, a public preset, or a 300-subject feasibility claim.

Verify without executing a benchmark:

```powershell
diffeoforge modern-benchmark-design-verify `
  reference/modern-engine-v0.5/paired-standard-recompute-design
```

## Completed raw execution

After the design had been archived in commit `ad478e7`, its six frozen
conditions were executed into `paired-standard-recompute-run`. The run contains
five measured fresh-process observations plus one warm-up for each condition.
All six JSON/CSV/HTML report triplets, the atomic state, lifecycle events, and
the final `study-run.json` SHA-256 sidecar pass strict verification. A repeated
runner invocation left all 26 files byte-identical.

The completion manifest records `analysis_performed: false`. These files are
raw engineering evidence only. No speedup, memory advantage, ranking,
statistical significance, full-atlas runtime, convergence, public preset, or
large-cohort feasibility conclusion is declared here.

Verify the completed run without modifying it:

```powershell
diffeoforge modern-benchmark-study-verify `
  reference/modern-engine-v0.5/paired-standard-recompute-run
```
