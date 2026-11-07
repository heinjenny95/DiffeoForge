# Public paired CPU observations — 14 September 2026

All **36 fresh workers passed** the prospective input, provenance, repeatability
and numerical gates. Ten objective/trajectory/gradient fields were compared;
the largest absolute difference was **1.4210854715202004e-14**, within the unchanged
symmetric `atol=1e-10`, `rtol=1e-8` rule. This is a small synthetic implementation
benchmark, **not a full-atlas or biological validation**.

Source: [0b555d83f587aed8fd4a11d19aa627d3dd06f3fd](https://github.com/heinjenny95/DiffeoForge/commit/0b555d83f587aed8fd4a11d19aa627d3dd06f3fd).
Read the [prospective protocol](../../docs/PUBLIC_ENGINE_PAIR.md), including its
two rejected capture corrections, before interpreting these measurements.

## All conditions

Each timing is the median of three fresh-process medians, in milliseconds;
brackets contain the observed minimum–maximum of those process medians. Each
process has one untimed warmup and three timed objective-plus-gradient evaluations.

| Attachment / faces | Deformetrica KeOps | Modern dense | Modern blockwise recompute |
| --- | ---: | ---: | ---: |
| Current / 320 | 12.69 [12.50–12.80] | 11.47 [11.07–11.92] | 18.63 [18.60–18.63] |
| Current / 1,280 | 87.28 [87.27–88.16] | 123.12 [113.40–126.34] | 69.77 [67.49–70.27] |
| Varifold / 320 | 17.08 [17.03–17.17] | 12.94 [12.34–13.30] | 23.53 [22.80–23.59] |
| Varifold / 1,280 | 152.30 [151.33–153.83] | 191.51 [139.13–193.47] | 117.31 [111.06–121.32] |

Maximum whole-worker peak resident memory across the three processes, in MiB:

| Attachment / faces | Deformetrica KeOps | Modern dense | Modern blockwise recompute |
| --- | ---: | ---: | ---: |
| Current / 320 | 361.63 | 240.64 | 304.76 |
| Current / 1,280 | 363.55 | 346.93 | 307.36 |
| Varifold / 320 | 363.36 | 247.78 | 306.88 |
| Varifold / 1,280 | 365.57 | 447.94 | 332.00 |

At 1,280 faces the blockwise mode was approximately 20% (Current) and 23%
(Varifold) faster than the reference; at 320 faces it was slower. Dense Varifold
at 1,280 faces had a wide timing range and used more peak RSS than the reference.
These observations do not establish statistical significance or general scaling.

## Provenance and limitations

- AMD Ryzen 9 7950X, WSL2 Linux 6.18.33.2, x86_64, CPU float64, one thread.
  Reference: Python 3.8.20, Torch 1.6.0+cpu, NumPy 1.24.4, Deformetrica 4.3.0,
  KeOps 1.4.1. Modern: Python 3.12.3, Torch 2.13.0+cpu, NumPy 2.5.1.
- Only the public CC0 template and one subject. Subdivision preserves the same
  piecewise-planar surface; it does not add anatomical information. The largest
  mesh has only 1,280 faces. No private datasets were used.
- Float64 reference surface caches are explicitly invalidated as specified in
  the protocol; this is not a test of unchanged native float64 CLI behavior.
- RSS includes runtime imports and warmup, excludes child compiler processes,
  and is not tensor-only memory or an evaluation increment. Runtime overheads differ.
- No optimizer-convergence, large-mesh, GPU/HPC, native installer or biological
  conclusion. This experiment does not close the separate float32 legacy CPU gate.

All 36 JSON observations and SHA-256 sidecars are retained, alongside the exact
comparison. An independent Windows-host re-comparison of the same observations
produced byte-identical JSON (SHA-256
`88db2cd785e91fa6eaa5095af32945f6f58893ba793b54de3c374861e4c168ae`).
The retained-evidence test verifies every sidecar and rederives the comparison.

```powershell
python tools/benchmark_engine_pair.py compare --directory reference/public-engine-pair-v1/observations --output /new/path/comparison.json
```

Output paths must not already exist. Raw observations, timing ranges and failures
must not be replaced to improve the apparent result.
