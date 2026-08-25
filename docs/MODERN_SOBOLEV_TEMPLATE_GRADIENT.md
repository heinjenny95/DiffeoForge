# Modern Sobolev template-gradient kernel

Status: **implemented as an explicit Engine 1.6 workflow option; real-cohort
non-inferiority qualification still required**

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

The remaining prospective scientific/engineering gate must:

1. freeze a new same-cohort full-atlas design with `template_gradient: sobolev`
   and ratio `1.0` before observing its result;
2. run it on the declared CUDA/float64 environment;
3. require verified convergence, exact continuation if needed, and every
   predeclared external template/reconstruction gate; and
4. compare it with both the completed Deformetrica atlas and the separately
   frozen Engine 1.5 Euclidean-gradient baseline without selecting whichever
   result looks preferable after the fact.
