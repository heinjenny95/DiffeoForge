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
