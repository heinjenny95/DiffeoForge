# Modern objective/gradient benchmark protocol

Status: **implemented measured microbenchmark; not a full-run predictor**

Tracked prospectively by
[engineering issue #38](https://github.com/heinjenny95/DiffeoForge/issues/38)
and extended for configured blockwise execution by
[engineering issue #46](https://github.com/heinjenny95/DiffeoForge/issues/46).
Benchmark-only effective tile plans are tracked by
[engineering issue #64](https://github.com/heinjenny95/DiffeoForge/issues/64).

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
the workflow. Without tile-size overrides, version 0.3 executes the exact dense
or blockwise pairwise plan declared in the reviewed configuration. It rejects
Procrustes-enabled configurations because it benchmarks the numerical objective
directly rather than pretending to measure the preprocessing pipeline.

The default output is `modern-atlas.benchmark/`:

```text
modern-atlas.benchmark/
  benchmark.json
  samples.csv
  benchmark.html
```

The directory is not overwritten by default. `--force` replaces only a
recognized generated directory containing exactly those three files.

## Benchmark-only autograd strategy

Standard autograd remains the default and the only strategy carried by the
reviewed atlas workflow configuration. A configured blockwise benchmark may
explicitly override the measured tile plan to `recompute`:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml `
  --subjects 5 --tile-autograd-strategy recompute `
  --output modern-atlas.recompute-benchmark
```

Dense execution with `recompute` fails before a worker is spawned because there
are no tiles to recompute. The strict report stores
`configuration.tile_autograd_strategy`. To collect standard and recompute
observations, run two commands with separate output directories. DiffeoForge
does not combine them, select a winner, calculate a speedup, or convert them
into a workflow setting.

## Benchmark-only effective tile shape

A reviewed blockwise configuration can measure one explicit effective
query/source tile shape without editing the hashed YAML:

```powershell
diffeoforge modern-benchmark modern-atlas.yaml `
  --subjects 5 --query-tile-size 128 --source-tile-size 256 `
  --output modern-atlas.tiles-128x256.benchmark
```

Both tile options are mandatory together and must be positive integers. A
partial override, dense base configuration, or invalid dimension fails before
any worker starts. Supplying both options selects strict benchmark report v0.4.
Its configuration records the source-declared blockwise plan separately from
the effective benchmark-only plan. The effective plan crosses the fresh-process
spawn boundary explicitly and drives the Gaussian worker, operation model,
largest execution tile, and review HTML.

This does not rewrite the source YAML or change `PairwiseEvaluationPlan`,
`modern-run`, atlas estimation, reconstruction, or PCA. Omitting both options
continues to produce the existing v0.3 shape. Existing v0.1 paired-study designs
and runners intentionally continue to require and produce v0.3 reports; the
multi-tile matrix is a later versioned gate.

## What one repeat measures

Every repeat uses a fresh process created with Python's cross-platform
`multiprocessing` spawn context. Inside that process DiffeoForge:

1. resolves the selected template and subject prefix;
2. constructs CPU float64 tensors and deterministic farthest-template control
   points exactly as the modern workflow does;
3. applies the configured PyTorch thread count and random seed;
4. applies the declared plan, or the separately recorded effective
   benchmark-only tile plan, plus the explicit autograd strategy to every
   Gaussian operation;
5. performs the declared number of unmeasured warm-up evaluations;
6. starts a 5 ms process-RSS sampler;
7. measures one atlas objective and one gradient for the first configured
   optimizer block with `perf_counter_ns`; and
8. returns only finite numerical and resource observations.

Tensor/input preparation and warm-up are outside the wall-time interval. The
absolute sampled RSS still includes the prepared process, tensors, imported
libraries, and allocator state present after warm-up. `sampled_rss_delta` is
the nonnegative difference from the working set immediately before the timed
evaluation; allocator retention can make it small or zero.

RSS is obtained through the cross-platform
[psutil process API](https://psutil.readthedocs.io/stable/#processes), pinned to
the current 7.x major in the modern-engine dependency set.

## Auditable evidence

Strict `modern-benchmark-v0.3.json` records the source-declared plan. Strict
`modern-benchmark-v0.4.json` retains the same observation contract and records
both source-declared and effective benchmark-only blockwise plans. Reports also
record:

- config and selected input SHA-256 values, filenames, points, triangles, and
  deterministic selection rule;
- Python, DiffeoForge, NumPy, PyTorch, psutil, operating-system, CPU-thread,
  random-seed, and physical-memory observations;
- warm-up/repeat counts, process-isolation method, and sampling interval;
- the benchmark-only standard/recompute strategy;
- the exact logical Gaussian calls/pair elements, largest logical pair, and
  largest configured execution tile from the versioned workload model for
  this selected subset;
- every raw wall-time/RSS/objective/gradient repeat;
- minimum, median, and maximum descriptive summaries; and
- the declared numerical consistency tolerance and observed spans.

CSV is a direct open handoff of the repeat rows. HTML is an escaped review
view. Measurements are inherently not byte-repeatable; configuration,
selection, software, protocol, and raw observations are preserved so they can
be independently interpreted. Schema validation and semantic arithmetic checks
reject inconsistent repeat, summary, numerical, logical-pair, or execution-tile
records before publication.

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

A dense/blockwise or tile-size comparison additionally requires separate
reports for every prospectively declared configuration under the same frozen
protocol. One faster repeat or lower sampled RSS value is not evidence of a
causal performance difference, and a blockwise tile bound is not a measured
peak-memory bound.

The same applies to standard/recompute comparisons. Recompute changes backward
work and the saved-tensor graph; a defensible tradeoff requires prospectively
declared repeat counts, controlled order, representative meshes and subject
counts, and separate end-to-end evidence. Benchmark support and spawn smoke
tests alone are not performance validation.

`modern-benchmark-design` v0.1 now creates the immutable pre-results half of
that protocol: config/input hashes, paired subject-prefix sizes, repeats,
warm-ups, exact condition order, separate intended report directories, and the
analysis boundary. It performs no measurements. See the
[prospective paired benchmark-design protocol](MODERN_BENCHMARK_STUDY.md).

`modern-benchmark-study` can execute or resume that exact stored sequence. It
revalidates config/input identity and preserves every condition as its own
strict v0.3 report, then hashes those artifacts into a completion manifest. It
does not combine or interpret the measurements.
