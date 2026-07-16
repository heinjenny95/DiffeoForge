# Modern engine feasibility baseline

Status: **experimental; not a production atlas backend**

Tracked by [scientific-change issue #12](https://github.com/heinjenny95/DiffeoForge/issues/12).

## Decision summary

DiffeoForge will develop a focused deterministic 3D surface-atlas engine instead
of porting every Deformetrica feature. Dense PyTorch operations form the first
correctness baseline. They are intentionally transparent and differentiable,
but their quadratic kernel matrices are not expected to scale to a 300-subject
study without later acceleration.

PyKeOps or another accelerator may be added behind the same operations only
after it reproduces the dense baseline within declared tolerances. It is not a
mandatory dependency: the current PyKeOps 2.3 installation path requires a C++
compiler and its published package metadata does not advertise native Windows
support. This is incompatible with the eventual no-programming desktop install
if placed on the critical path.

The frozen Deformetrica 4.3.0 environment remains an independent behavioral
oracle. It is not treated as an unquestionable mathematical ground truth, and
its Python 3.8, PyTorch 1.6, and PyKeOps 1.4.1 dependency set is not copied into
the modern application.

## Evaluated routes

| Route | Use in DiffeoForge | Reason |
|---|---|---|
| Full Deformetrica dependency port | Rejected | Excess scope and recreates coupling to internals that the public backend boundary deliberately removes. |
| Focused reuse of Deformetrica equations | Accepted with attribution and comparison | Preserves the required deterministic surface path without promising unsupported models. |
| Dense current PyTorch implementation | Accepted as correctness baseline | Current Python support, CPU/Windows wheels, autograd, explicit tensor operations, and straightforward independent tests. |
| PyKeOps | Optional accelerator candidate | Appropriate for large kernel reductions, but compilation and platform constraints prevent it from being mandatory. |
| scikit-shapes | Independent research/design reference | Provides modern LDDMM and varifold components, but the current public task API exposes registration rather than atlas construction and its package documentation targets Linux/macOS. |

Primary project sources inspected for this decision:

- [Deformetrica repository](https://gitlab.com/icm-institute/aramislab/deformetrica)
  and [4.3.0 changelog](https://gitlab.com/icm-institute/aramislab/deformetrica/-/blob/master/CHANGELOG.md);
- [PyTorch installation documentation](https://docs.pytorch.org/get-started/locally/)
  and [PyTorch 2.13.0 package metadata](https://pypi.org/project/torch/2.13.0/);
- [PyKeOps installation documentation](https://www.kernel-operations.io/keops/python/installation.html)
  and [PyKeOps 2.3 package metadata](https://pypi.org/project/pykeops/2.3/);
- [scikit-shapes documentation](https://scikit-shapes.github.io/), including
  its [LDDMM example](https://scikit-shapes.github.io/scikit-shapes/auto_examples/registration/plot_lddmm_0_skulls.html)
  and [tasks API](https://scikit-shapes.github.io/scikit-shapes/stubs/skshapes.tasks.html).

## Implemented mathematical boundary

The experimental `diffeoforge.engine` module currently implements:

- the Deformetrica Gaussian convention
  `K(x, y) = exp(-||x-y||^2 / width^2)`;
- dense kernel convolution and its explicit derivative;
- deformation norm squared `p^T K(q,q) p`;
- Euler and midpoint-RK2 control-point/momenta shooting;
- Euler and standard Heun template-point flow;
- an explicitly named `deformetrica_heun` compatibility integrator that
  reproduces Deformetrica 4.3's final-step trajectory extrapolation;
- triangle centroids and oriented area-weighted normals;
- orientation-sensitive current squared distance;
- orientation-insensitive varifold squared distance;
- the complete per-subject deterministic-atlas contribution, with attachment
  `-distance / noise_variance`, regularity `-p^T K(q,q) p`, and their sum;
- an unaveraged, order-preserving multi-subject objective sum.
- a deterministic momenta-only gradient-ascent prototype with Armijo
  backtracking and complete accepted-state history.
- a deterministic full-parameter block optimizer for per-subject momenta,
  shared template vertices, and shared control points, with an explicit Armijo
  line search and decision history for every block.
- a companion immutable result-bundle contract with estimated template and
  reconstructed subject meshes, open parameter/history tables, complete file
  hashes, and an automatic momenta-PCA handoff.

All public operations require finite, three-dimensional floating-point tensors,
matching dtype/device, finite positive kernel widths, and valid zero-based
`int64` triangle connectivity. They do not silently cast inputs. Degenerate
zero-area faces fail explicitly.

This boundary does **not** yet include automatic control-point initialization,
optimizer checkpointing, GPU execution, sparse/chunked kernels, mesh-quality
constraints, or a workflow-backend adapter.

## Evidence in this baseline

The modern-engine test suite covers:

- hand-checkable Gaussian values;
- primitive outputs generated by the frozen Deformetrica 4.3.0 CPU environment;
- Current and Varifold distances generated by that reference environment;
- full endpoint surfaces, objective components, and template/control-point/
  momenta gradients for both attachment types;
- the explicit kernel derivative against PyTorch autograd;
- a double-precision finite-difference gradcheck of the varifold distance;
- a finite-difference gradcheck through the complete subject objective;
- deterministic and unaveraged multi-subject objective assembly;
- deterministic repeated shooting;
- non-mutation of inputs;
- zero-momenta stationary trajectories;
- translation invariance;
- current versus varifold behavior under reversed triangle orientation;
- invalid dimensions, dtypes, widths, integrators, indices, and degenerate faces.

The versioned fixture
`reference/modern-engine-v0.1/deformetrica-4.3.0-primitives.json` records inputs,
reference outputs, environment versions, source components, and provisional
operation-level tolerances. The comparison command emits runtime provenance,
the fixture SHA-256, and per-operation errors as JSON:

```bash
python -m pip install -e ".[dev,modern-engine]"
python -m diffeoforge.engine.reference \
  reference/modern-engine-v0.1/deformetrica-4.3.0-primitives.json \
  --output modern-engine-comparison.json
```

On the first Windows CPU run with Python 3.12.13 and PyTorch 2.13.0, five of
the six recorded operations were identical to the Deformetrica 4.3 fixture;
the maximum remaining absolute error was approximately `3.47e-18` for the
explicit kernel gradient. This is primitive-level feasibility evidence only.

The v0.2 fixture
`reference/modern-engine-v0.2/deformetrica-4.3.0-objective.json` extends that
evidence through both surface attachments and the complete differentiable
subject chain. On Windows with Python 3.12.13 and PyTorch 2.13.0, all 20 v0.2
comparisons passed; the largest absolute discrepancy was approximately
`1.25e-14`.

Two legacy behaviors are kept visible instead of being silently copied. First,
Deformetrica 4.3's RK2 flow evaluates its last Heun corrector at a control-point
state extrapolated one additional time step beyond its stored trajectory. The
modern module retains standard Heun and exposes the legacy behavior only under
the explicit name `deformetrica_heun`. Second, `SurfaceMesh` constructs and
caches target geometry in the global float32 default even for a later float64
model. The v0.2 generator deliberately marks targets for recomputation so the
fixture measures the float64 mathematical chain rather than this mixed-precision
constructor-cache artifact; that policy is recorded inside the fixture.

## Gates before a usable atlas engine

1. ~~Add current/varifold fixtures generated through the independent reference
   environment rather than only invariant tests.~~ Completed in v0.2.
2. ~~Assemble and differentiate the complete per-subject deterministic-atlas
   objective.~~ Completed in the dense correctness baseline.
3. ~~Prototype explicit optimization of momenta, template vertices, and shared
   control points.~~ Completed in the v0.4 CC0 block-optimizer evidence.
4. Compare objective components, endpoint surfaces, control-point trajectories,
   and gradients on CC0 meshes.
5. Add chunked or accelerated kernels and prove parity with the dense baseline.
6. Benchmark runtime and peak memory over mesh, control-point, and subject count.
7. Define evidence-derived tolerances before accepting a production backend.
8. Integrate the engine through immutable run manifests without weakening the
   existing reference workflow.

No scientific atlas result should be produced or interpreted through this
experimental module until these gates pass.
