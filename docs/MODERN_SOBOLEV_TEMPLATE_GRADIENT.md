# Modern Sobolev template-gradient kernel

Status: **isolated numerical kernel; not yet wired into a released Modern workflow**

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

`diffeoforge.engine.sobolev_template_gradient` now implements the isolated
operation with explicit dense or exact blockwise evaluation. Tests bind the
formula, dense/blockwise parity for standard and recompute tile strategies,
input immutability, detached output, dtype/device preservation, and strict
setting validation.

The convention was also checked numerically against the locally installed
Deformetrica 4.3 `TorchKernel.convolve` implementation on August 25, 2026. A
fixed three-point, three-vector fixture agreed component-wise to floating-point
roundoff at effective width `0.6`.

The kernel alone does not change a workflow or establish optimizer equivalence.
The remaining prospective integration gate must:

1. add an explicit versioned workflow setting rather than infer smoothing;
2. apply the transformed gradient only to the template block, including every
   candidate gradient used by Armijo/L-BFGS;
3. serialize the setting in bundles and complete-cycle checkpoints;
4. prove unchanged Euclidean-mode behavior and exact continuation;
5. run a new same-cohort full-atlas comparison against Deformetrica.
