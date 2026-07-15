# Experimental momenta-only optimizer

Status: **correctness prototype; not a complete atlas estimator**

Tracked by [scientific-change issue #16](https://github.com/heinjenny95/DiffeoForge/issues/16).

## Frozen scope

The first modern optimizer varies one momenta matrix per subject while keeping
the template vertices and shared control points fixed. This establishes that
the validated differentiable objective can be improved reproducibly. It does
not yet estimate a population template and must not be described as equivalent
to Deformetrica's optimizer.

For current momenta `p` and gradient `g`, a candidate is

`p_candidate = p + step_size * g`.

The implementation accepts it only if the ascent Armijo condition holds:

`objective_candidate >= objective_current + c * step_size * ||g||^2`.

Rejected candidates are discarded. The step is multiplied by a declared
backtracking factor until a candidate passes or the line-search limit/minimum
step is reached. There is no hidden optimizer state, momentum term, adaptive
learning rate, or stochastic batching.

## Observable result

Every accepted state records:

- iteration number;
- total objective, attachment, and regularity;
- one surface residual per subject in input order;
- gradient norm;
- accepted step size;
- number of line-search evaluations.

The result also records the termination reason, convergence flag, total
line-search evaluations, and a detached copy of the last accepted momenta.
Failed line searches cannot mutate the input or overwrite the last accepted
state.

## Versioned CC0 smoke evidence

`tools/run_modern_optimizer_smoke.py` reads the committed five-subject CC0
cohort, uses nine explicitly indexed fixed control points, and runs three
float64 CPU iterations. Its settings, input hashes, history, final-momenta
hash, runtime provenance, and scientific boundary are frozen in
`reference/modern-engine-v0.3/cc0-momenta-smoke.json`.

```bash
python -m pip install -e ".[dev,modern-engine]"
python tools/run_modern_optimizer_smoke.py --output optimizer-smoke.json
```

In the first Windows/Python 3.12/PyTorch 2.13 run, the accepted objective
sequence was `-44.0713892`, `-12.7626978`, `-7.4385235`, and `-5.8421017`.
Each iteration accepted step size `0.00125` after four line-search evaluations.
This is deterministic engineering evidence on non-biological data, not a
scientific atlas result or a performance benchmark.

## Tests and limits

The tests cover monotonic accepted objectives, exact same-runtime repeatability,
stationary and zero-iteration cases, explicit backtracking, failed-line-search
state preservation, execution under an outer `no_grad` context, invalid
settings, non-finite inputs, and tolerance-based replay of the CC0 smoke
fixture on Windows and Linux CI.

Remaining gates include template/control-point initialization and optimization,
output meshes, convergence studies, matched Deformetrica optimizer experiments,
chunked/accelerated kernels, memory/runtime benchmarks, checkpointing, and
workflow-backend integration.
