# Prospective optimizer scaling design

## Purpose

`modern-optimizer-benchmark-design` freezes subject-prefix sizes, optimizer
cycle caps, repeats, warm-ups, input hashes, configuration, and condition order
before any result exists. It is the pre-registration layer for the versioned
multi-cycle optimizer benchmark and prevents convenient conditions from being
added only after inspecting timings or sampled memory.

Creating or verifying a design runs no optimizer.

## Create and verify

```powershell
diffeoforge modern-optimizer-benchmark-design modern-atlas.yaml `
  --subjects 5 20 68 `
  --cycles 1 3 `
  --repeats 3 `
  --warmups 0 `
  --order-seed 20260722

diffeoforge modern-optimizer-benchmark-design-verify `
  modern-atlas.optimizer-study
```

The complete factorial is mandatory:

```text
conditions = subject-prefix levels × cycle-cap levels
```

The example freezes six conditions. Subject counts cannot exceed the complete
hashed inventory and follow its deterministic path order. Cycle caps are
benchmark-only values; the reviewed YAML and its source cycle setting remain
unchanged. The design limits mirror the benchmark: at most 1,000 subjects, 100
cycles, 50 repeats, and 10 complete warm-up runs per repeat. A separate
1,000-condition ceiling catches accidental factorial explosions; it is not a
runtime forecast.

## Immutable contents

The new directory contains exactly:

- `optimizer-design.json`, the strict v0.1 machine-readable design;
- `optimizer-design.sha256`, binding the JSON bytes; and
- `optimizer-design.html`, a deterministic escaped review page.

Publication is atomic and never overwrites an existing path. The read-only
verifier rejects missing or added files, sidecar changes, schema drift,
condition-count changes, reordered or edited conditions, and HTML that differs
from deterministic regeneration.

## Execute, resume, and verify

After the design is frozen, execute it against the unchanged source config:

```powershell
diffeoforge modern-optimizer-benchmark-study `
  modern-atlas.optimizer-study modern-atlas.yaml

diffeoforge modern-optimizer-benchmark-study-verify `
  modern-atlas.optimizer-study.run
```

The executor freshly rebuilds the design from the current config and complete
mesh inventory before creating or resuming a run. Any YAML, mesh, software,
factor, or deterministic-order difference fails before a condition starts.

Each condition calls the versioned optimizer benchmark, which already uses a
fresh spawned process for every repeat. Raw JSON, CSV, and HTML stay in their
own frozen condition directory. After each condition, its strict report is
verified before state and the append-only event log advance.

The run owns a process-identity lock, copied design, copied source config,
atomic state, append-only events, condition directories, and a final
`optimizer-study-run.json` plus SHA-256 sidecar. After an interruption, only a
contiguous prefix of strictly valid raw reports can be reconciled; unknown,
out-of-order, or changed entries fail closed. Re-running a completed study is a
read-only re-verification.

The completed-run verifier checks every nested raw report against its frozen
subject prefix, cycle cap, repeats, warm-ups, optimizer settings, source hash,
and mesh inventory. It then recomputes the final artifact hashes and event
order. No aggregate ranking or performance summary is generated.

The design hashes the source YAML and every available template/subject mesh. It
also records the attachment and integration choices, pairwise plan, optimizer
block order and line-search settings, control-point/timepoint counts, CPU thread
count, and random seed. Each condition stores an exact argv with the verified
config placeholder and a separate relative raw-report directory.

## Deterministic order and analysis policy

`sha256-ranked-subject-cycle-cells-v0.1` ranks stable cell IDs from the declared
order seed. The order is reproducible but not selected from observed results.

The frozen analysis policy preserves every separate raw optimizer report and
allows descriptive time, sampled RSS, work-counter, termination, and repeat
consistency reporting. It prohibits automatic winner selection, ETA fitting,
extrapolation beyond observed cells, or a convergence claim.

## Scientific boundary

The design itself contains no optimization, timing, memory sample, result,
comparison, recommendation, or statistical inference. Nested subject prefixes
are not independent cohorts; cycle caps are not proof of convergence; sampled
RSS is not guaranteed peak memory. The executor verifies the design, source
config, and complete input inventory before running and retains every raw v0.1
optimizer benchmark separately. A future analysis layer must be designed and
frozen independently; the executor does not infer one.
