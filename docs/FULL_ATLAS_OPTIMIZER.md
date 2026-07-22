# Experimental full atlas optimizer

Status: **dense CPU correctness prototype; not a production atlas estimator**

Tracked prospectively by
[scientific-change issue #24](https://github.com/heinjenny95/DiffeoForge/issues/24).

## Declared parameterization

The optimizer maximizes the already validated multi-subject objective over
three explicit parameter blocks:

1. one initial momenta matrix per subject;
2. one shared template-vertex matrix;
3. one shared control-point matrix.

Triangle connectivity, target surfaces, kernel widths, noise variance,
attachment type, and numerical integrators remain fixed during a run. The
default block order is `momenta`, `template`, then `control_points`; callers may
declare another permutation, which is recorded exactly. Omitting a block is
not allowed in this full-parameter entry point. The earlier
`optimize_momenta` function remains available for a deliberately frozen
template/control-point experiment.

Because the observed target surfaces are fixed, their triangle geometry and
quadratic attachment self terms are prepared once per optimizer invocation and
reused without approximation. Source-dependent and cross terms are still
recomputed, and exact dense/blockwise value and gradient parity is tested. See
[prepared fixed-target attachments](PREPARED_ATTACHMENT_TARGETS.md).

## Transparent block update

For current block value `x`, gradient `g`, and proposed step `s`, the candidate
is

`x_candidate = x + s * g`.

The candidate is accepted only when

`objective_candidate >= objective_current + c * s * ||g||²`.

Otherwise, `s` is multiplied by the declared backtracking factor and tried
again. Each parameter block has its own initial step size because their units
and gradient scales differ. There is no adaptive learning rate, stochastic
batching, momentum term, or hidden optimizer state.

Candidate objectives are evaluated before their gradients. A rejected Armijo
candidate releases its graph without an unused backward pass; an acceptable
candidate requests the gradient from the same graph without repeating its
forward pass. The initial evaluation is reused for the first block. This
changes scheduling only: the objective, candidate sequence, acceptance rule,
accepted states, and recorded history remain identical. See
[deferred Armijo gradients](DEFERRED_ARMIJO_GRADIENTS.md).

One cycle visits every block once. If every block gradient is below the
declared threshold in the same cycle, the run terminates as converged. A
line-search failure terminates the prototype without overwriting any accepted
parameter. Reaching the cycle limit is reported separately and is not called
convergence.

## Observable result contract

The returned final template vertices, control points, and momenta are detached
copies. Every optimizer decision records:

- cycle and parameter block;
- `initial`, `accepted`, `stationary`, or `failed` status;
- total objective, attachment, regularity, and ordered subject residuals;
- gradient norm;
- accepted step size, if any;
- number of line-search evaluations.

The result additionally records the termination reason, failed block, completed
cycles, convergence flag, and total line-search evaluations. Caller-owned
inputs are never mutated.

## Versioned CC0 evidence

`tools/run_full_atlas_optimizer_smoke.py` exercises three complete cycles on
the committed five-subject CC0 cohort. Each surface contains 162 vertices and
320 triangles; nine shared control points are selected by explicit indices.
The input hashes, settings, runtime provenance, history, final-parameter hashes,
parameter-displacement norms, and scientific boundary are frozen in
`reference/modern-engine-v0.4/cc0-full-atlas-smoke.json`.

```bash
python -m pip install -e ".[dev,modern-engine]"
python tools/run_full_atlas_optimizer_smoke.py --output full-atlas-smoke.json
```

In the first Windows float64 CPU run, all nine block updates were accepted.
The objective sequence after each complete cycle was approximately `-12.4494`,
`-6.9924`, and `-5.3266`, compared with `-44.0714` initially. Template,
control points, and momenta all moved. These values are deterministic
engineering regression evidence on non-biological data, not a scientific
atlas result or a convergence/performance benchmark.

## Tests and scientific limits

Tests cover monotonic accepted states, exact same-runtime repeatability,
input immutability, detached outputs, fully stationary data, zero cycles,
line-search rollback, declared block order, outer `no_grad` execution, invalid
settings, non-finite inputs, and tolerance-based replay of the CC0 evidence.
The existing Deformetrica v0.2 fixture independently checks template,
control-point, and momenta gradients through the full subject objective.

This prototype does **not** establish:

- optimizer-trajectory or final-template equivalence with Deformetrica;
- global convergence or robustness to initialization;
- mesh quality, non-self-intersection, or topology preservation;
- acceptable runtime or memory use for 300 subjects;
- GPU parity;
- suitability for biological inference.

The [modern atlas bundle](MODERN_ATLAS_BUNDLE.md) now exports the accepted final
state and reconstructed endpoints without changing this optimizer contract;
the [experimental modern workflow](MODERN_WORKFLOW.md) now connects ordinary
mesh directories to both. The next gates are matched optimizer experiments,
mesh-quality safeguards, checkpoint serialization, convergence studies, and
chunked or accelerated kernels with parity evidence.
