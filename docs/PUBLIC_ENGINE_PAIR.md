# Public CPU engine comparison protocol v1

Prospectively specified on 14 September 2026, before this protocol's paired
observations. This is a bounded implementation benchmark, not atlas qualification.

- Only the hash-checked CC0 synthetic template and subject-01 are used. Two sizes:
  the original 162 vertices / 320 faces, and one deterministic unsmoothed midpoint
  subdivision (642 vertices / 1,280 faces). Subdivision changes discretization,
  not the represented piecewise-planar surface or anatomical information.
- One subject, 27 fixed control points, explicitly nonzero deterministic momenta,
  CPU/float64, one thread, five timepoints, RK2 shooting and Deformetrica's Heun
  flow convention. Deformation width 1, attachment width 0.5, noise variance 0.25.
  These exactly representable widths avoid the legacy KeOps float32 gamma cache
  as a confound. They are engineering inputs, not recommended biological settings.
- Current and Varifold; frozen Deformetrica 4.3.0 / Torch 1.6.0+cpu / KeOps 1.4.1
  against Modern Torch 2.13.0 dense and 128-by-128 blockwise recompute evaluation.
- As in the existing v0.2 objective reference, explicitly invalidate Deformetrica's
  constructor-only float32 surface cache for the float64 experiment. This does not
  patch the installed engine and does not describe unmodified float64 CLI behavior.
- All modes reuse fixed-target terms. One untimed forward/backward warmup, then
  three timed objective-plus-gradient evaluations per fresh process, three fresh
  processes per condition: 36 workers, sequential on one Linux host. Rotate mode
  order between repetitions. Imports, target setup, JIT compilation and JSON
  conversion are outside timed evaluation; kernel caches may be warm.
- Compare total, residual, attachment, regularity, endpoints, both complete shooting
  trajectories and all three parameter gradients. Require identical outputs across
  repetitions; use predeclared symmetric `atol=1e-10`, `rtol=1e-8` between modes.
  Preserve failures. Neither reference/synthetic-v1 nor its thresholds is changed.
- Retain all timings. Report the median of three process medians and its observed
  min/max, without a statistical significance or full-atlas speedup claim.
- Memory is Linux `ru_maxrss` for the **whole worker**, including imports and warmup,
  excluding child compiler processes. It is not tensor-only or a per-evaluation
  increment. Runtime/library overhead differs between the two stacks.
- Reports and SHA-256 sidecars are immutable. The comparator requires all 36 unique
  conditions, consistent input/host/worker provenance, finite values and timing,
  matching structures and fresh-process repeatability.

Metadata correction before numerical assessment: the first 36-worker capture
was rejected because `platform.platform()` included different libc labels from
the two Python builds (2.38 versus 2.39) on the same WSL kernel. Host identity
now compares explicit system/kernel/machine fields and CPU model; runtime-specific
platform labels remain recorded separately. All 36 workers are recollected;
the initial rejected files remain intact. No workload or numeric threshold changes.

Use `tools/benchmark_engine_pair.py observe --help` in each isolated interpreter,
with `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` before import and the repository `src`
directory on `PYTHONPATH` for Modern. Use the `compare` command only after every
worker finishes; put its output outside the observation directory.

No private data, installed app changes, engine replacement, native installers,
GPU/HPC certification, optimizer-convergence or biological claims are authorized
by this protocol. A failed comparison must be investigated before optimization.
