# Modern ordered-landmark attachment

Status: **implemented as an explicit Engine 1.7 workflow option; first
prospective synthetic qualification passed**

Engine 1.7 adds `model.attachment.type: landmark` for datasets whose meshes
already have exact ordered point correspondence. For a deformed template
endpoint `x` and target vertices `y`, the residual is

`sum_i ||x_i - y_i||^2`.

The ordinary attachment contribution remains `-residual / noise_variance` and
the deformation regularity is unchanged. The attachment kernel width remains a
positive recorded configuration field for schema and bundle compatibility but
is not used by the landmark residual.

Create an explicit configuration with:

```text
diffeoforge modern-init MESH_DIRECTORY --template TEMPLATE.vtk \
  --units unitless --attachment-type landmark
```

The workflow fails before optimization unless every subject has the same
vertex count and exact ordered triangle connectivity as the template. This is
deliberately strict: equal vertex counts alone do not establish correspondence,
and DiffeoForge does not infer ordered homology from filenames, remeshing, or a
trait CSV.

The existing `current` default and opt-in `varifold` mode are unchanged. Those
surface attachments are appropriate when point labels are not known, but they
must not be interpreted as observing exact target vertex identities. In
particular, tangential reparameterization can leave a surface match good while
ordered point error remains high.

Engine 1.7 permits exact continuation from Engine 1.5 and 1.6 for their
unchanged attachment modes. Older engines cannot have produced a landmark-mode
checkpoint. Compatibility remains an explicit allow-list.

## Scientific boundary

Landmark attachment is meaningful only when ordered vertices are genuinely
homologous by construction or independent curation. It is not a method for
creating correspondence from arbitrary meshes and is not automatically
appropriate for the 236-subject Trochanter cohort. The analytic synthetic
recovery study can opt into it with
`modern-synthetic-recovery-init --attachment-type landmark`; its prospective
result must be kept separate from the completed Engine 1.6 Current result.

## First prospective qualification, 27 August 2026

The frozen 12-subject analytic design used Engine 1.7, CPU/float64, nine
control points, L-BFGS, a 100-cycle cap, and the same predeclared gates as the
earlier Current experiment. The Euclidean and Sobolev arms differed only in the
template-gradient mode. Both immutable runs and the independently recomputed
assessment verify.

Both arms passed every gate and converged by relative-objective tolerance:

- Euclidean converged in 45 cycles, reduced pooled ordered-vertex RMSE by
  `82.1042%`, achieved reconstruction p95 `0.00660297` of the template
  diagonal, and template p95 `0.00589772`;
- Sobolev converged in 44 cycles, reduced RMSE by `82.1388%`, achieved
  reconstruction p95 `0.00656287`, and template p95 `0.00589413`.

The predeclared requirements were at least 50% RMSE reduction, reconstruction
p95 at most `0.02`, template p95 at most `0.02`, verified workflows, and
explicit convergence. Sobolev-minus-Euclidean reconstruction RMSE and p95 were
`-0.00000605735` and `-0.0000400990` of the diagonal. These very small deltas
do not support a superiority claim.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-landmark-template-gradient-recovery-design-v0.1`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-landmark-template-gradient-recovery-design-v0.1-euclidean-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-landmark-template-gradient-recovery-design-v0.1-sobolev-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-landmark-template-gradient-recovery-assessment-v0.1`

This passes a miniature known-correspondence engineering test. It does not show
that the empirical Trochanter meshes possess ordered vertex homology and does
not authorize landmark attachment for them without independent evidence.
