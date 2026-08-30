# Modern ordered-landmark attachment

Status: **implemented as an explicit Engine 1.7 workflow option; prospective
synthetic qualification pending**

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
