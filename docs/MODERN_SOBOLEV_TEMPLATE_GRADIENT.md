# Modern Sobolev template-gradient kernel

Status: **implemented as an explicit Engine 1.6 workflow option and passing a
prospective 236-subject 5k full-atlas non-inferiority gate; still opt-in**

Deformetrica 4.3 optionally transforms the Euclidean template-point gradient
before an optimizer update. For current template points `T`, raw gradient `g`,
deformation-kernel width `w`, and declared ratio `r`, the transformed gradient
is

`K(T, T; w * r) g`,

where DiffeoForge and Deformetrica use the same Gaussian convention
`K(x, y; s) = exp(-||x-y||^2 / s^2)`.

The completed 236-subject Deformetrica reference atlas used Sobolev gradients
with ratio `1.0`, so its effective smoothing width was the deformation width
`0.160656159003468`. The first prospective Engine 1.5 full-atlas qualification
was deliberately frozen before this operator was integrated and therefore
remains a transparent Euclidean-template-gradient baseline.

`diffeoforge.engine.sobolev_template_gradient` implements the numerical
operation with explicit dense or exact blockwise evaluation. Tests bind the
formula, dense/blockwise parity for standard and recompute tile strategies,
input immutability, detached output, dtype/device preservation, and strict
setting validation.

The convention was also checked numerically against the locally installed
Deformetrica 4.3 `TorchKernel.convolve` implementation on August 25, 2026. A
fixed three-point, three-vector fixture agreed component-wise to floating-point
roundoff at effective width `0.6`.

Engine 1.6 wires the operator into every template-gradient evaluation used by
steepest-ascent or L-BFGS updates, including line-search candidate gradients.
The public workflow configuration records `template_gradient` as `euclidean`
or `sobolev` and records `sobolev_kernel_width_ratio` explicitly. The generated
default remains `euclidean`; no existing workflow silently changes modes.
Bundles serialize both settings, and exact-state continuation requires the
same effective optimizer contract. Engine 1.6 explicitly allows exact
continuation from Engine 1.5 only because the legacy configuration resolves to
the unchanged Euclidean mode; all other cross-version resumes fail closed.

## Passing prospective 236-subject full-atlas gate

The same-cohort Sobolev design was frozen before either full-atlas result was
selected. It bound all 236 subjects, the same initial template and parameters,
Engine `1.6`, CUDA/float64, `template_gradient: sobolev`, and ratio `1.0`.
It converged without continuation after 26 cycles by
`relative_objective_tolerance`. All 104 optimizer decisions were accepted, the
objective trajectory was non-decreasing, and the final objective was
`-316.181246888669` (attachment `-159.879914424502`, regularity
`-156.301332464167`). Raw objectives are not compared across engine
implementations because their template-gradient parameterizations differ.

The independently recomputed assessment passed every predeclared gate:

- Modern workflow verification: pass;
- optimizer convergence: pass;
- subject pass fraction: `1.0`, or 236/236 (gate at least `0.8`);
- pooled Modern external-residual p95: `0.04280583636`, compared with
  `0.05681627348` for Deformetrica;
- pooled Modern/reference residual ratio: `0.7534080244` (gate at most `1.2`);
- cross-engine reconstruction p95/template diagonal: `0.02725017132` (gate at
  most `0.05`); and
- cross-engine template p95/reference diagonal: `0.03044631936` (gate at most
  `0.05`).

Every individual subject passed the residual-ratio gate of at most `1.25`. The
largest ratio was `1.032381516` for `6.0_z_00_Trochanter.vtk`.

Against the separately frozen Engine 1.5 Euclidean arm, Sobolev changed the
external metrics by:

- pooled Modern residual p95: `+0.00003821706`;
- pooled Modern/reference ratio: `+0.0006726428`;
- subject pass fraction: `+0.0042372881` (one additional passing subject);
- normalized cross-engine reconstruction p95: `+0.0005993607`; and
- normalized cross-engine template p95: `+0.0026938873`.

Thus both arms pass comfortably. The Sobolev arm removes the one Euclidean
subject-tail miss, while its pooled and cross-engine aggregate distances are
slightly higher under the frozen metrics. This trade-off does not establish
superiority of either arm, and no choice was made from PCA appearance.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine16-cuda-sobolev-full-atlas-qualification-v0.1-236-subject-modern-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine16-cuda-sobolev-full-atlas-qualification-v0.1-236-subject-assessment`

This establishes prospective engineering non-inferiority for the declared
236-subject cohort and protocol. It does not establish biological validity,
global optimality, PCA stability, a safe preset across anatomies, or production
readiness for an independent 300-subject dataset.

Paired numerical PCA stability can now be assessed separately with the
[Modern paired PCA stability](MODERN_PCA_STABILITY.md) artifact. That comparison
is intentionally not folded into this already frozen qualification decision and
does not turn score-space agreement into biological validation.

The desktop now exposes this mode as an explicit Modern-only choice alongside
the Euclidean baseline. It writes `template_gradient: sobolev` and the visible
positive width ratio into the reviewed configuration; the default remains
Euclidean. Selecting Sobolev does not cause DiffeoForge to infer anatomical
suitability from the Trochanter result, and the ordinary full-cohort and
external biological validation requirements remain unchanged.
