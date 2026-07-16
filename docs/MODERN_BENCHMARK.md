# Modern objective/gradient benchmark protocol

Status: **implemented measured microbenchmark; not a full-run predictor**

Tracked prospectively by
[engineering issue #38](https://github.com/heinjenny95/DiffeoForge/issues/38).

## Safe user path

The command requires an explicit subject count. It never defaults to the full
cohort:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml --subjects 5
```

Default protocol settings are one warm-up evaluation followed by three
measured repeats. They can be changed explicitly:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml `
  --subjects 5 --warmups 1 --repeats 5
```

The deterministic prefix comes from the same validated subject-path order as
the workflow. Version 0.1 rejects Procrustes-enabled configurations because it
benchmarks the numerical objective directly rather than pretending to measure
the preprocessing pipeline.

The default output is `modern-atlas.benchmark/`:

```text
modern-atlas.benchmark/
  benchmark.json
  samples.csv
  benchmark.html
```

The directory is not overwritten by default. `--force` replaces only a
recognized generated directory containing exactly those three files.

## What one repeat measures

Every repeat uses a fresh process created with Python's cross-platform
`multiprocessing` spawn context. Inside that process DiffeoForge:

1. resolves the selected template and subject prefix;
2. constructs CPU float64 tensors and deterministic farthest-template control
   points exactly as the modern workflow does;
3. applies the configured PyTorch thread count and random seed;
4. performs the declared number of unmeasured warm-up evaluations;
5. starts a 5 ms process-RSS sampler;
6. measures one atlas objective and one gradient for the first configured
   optimizer block with `perf_counter_ns`; and
7. returns only finite numerical and resource observations.

Tensor/input preparation and warm-up are outside the wall-time interval. The
absolute sampled RSS still includes the prepared process, tensors, imported
libraries, and allocator state present after warm-up. `sampled_rss_delta` is
the nonnegative difference from the working set immediately before the timed
evaluation; allocator retention can make it small or zero.

RSS is obtained through the cross-platform
[psutil process API](https://psutil.readthedocs.io/stable/#processes), pinned to
the current 7.x major in the modern-engine dependency set.

## Auditable evidence

Strict JSON records:

- config and selected input SHA-256 values, filenames, points, triangles, and
  deterministic selection rule;
- Python, DiffeoForge, NumPy, PyTorch, psutil, operating-system, CPU-thread,
  random-seed, and physical-memory observations;
- warm-up/repeat counts, process-isolation method, and sampling interval;
- the exact dense Gaussian calls/pair elements from the versioned workload
  model for this selected subset;
- every raw wall-time/RSS/objective/gradient repeat;
- minimum, median, and maximum descriptive summaries; and
- the declared numerical consistency tolerance and observed spans.

CSV is a direct open handoff of the repeat rows. HTML is an escaped review
view. Measurements are inherently not byte-repeatable; configuration,
selection, software, protocol, and raw observations are preserved so they can
be independently interpreted.

## Scientific boundary

The 5 ms sampler can miss shorter resident-memory peaks. RSS is not total
system memory, GPU memory, or a complete account of every allocator. The
timing covers one objective+gradient evaluation, not optimization,
reconstruction, PCA, quality verification, reporting, input copying,
Procrustes, or atomic publication.

No regression, asymptotic fit, ETA, pass/fail hardware label, or extrapolation
to 300 subjects is produced. A paper-grade feasibility claim still requires a
prospectively frozen multi-size design on representative simplified meshes,
multiple independent runs, full-workflow measurements, and explicit handling
of thermal, background-load, and cache effects.
