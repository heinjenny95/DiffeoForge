# Modern synthetic known-correspondence recovery

Status: **paired prospective workflow implemented; small evidence run pending**

DiffeoForge already generates independent analytic local, global, and mixed
surface deformations with exact ordered vertex correspondence. The Modern
synthetic-recovery workflow binds that ground truth to two full-atlas Engine
1.6 configurations:

- Euclidean template gradient;
- Sobolev template gradient with width ratio `1.0`.

Both arms use the same copied benchmark, initial template, control-point
selection, zero momenta, model, optimizer, seed, CPU/float64 runtime, and cycle
cap. The design verifier requires the configurations to be identical except for
the project/output labels and the declared template-gradient variable. A fresh
Euclidean arm is described as Engine 1.6 in Euclidean mode; it is not relabeled
as the historical Engine 1.5 implementation.

Create a known-correspondence benchmark and freeze the paired design before
either result exists:

```text
diffeoforge reference-validation-synthetic-create TEMPLATE.vtk \
  --output SYNTHETIC_BENCHMARK --subjects-per-family 4

diffeoforge modern-synthetic-recovery-init SYNTHETIC_BENCHMARK \
  --output RECOVERY_DESIGN

diffeoforge modern-synthetic-recovery-design-verify RECOVERY_DESIGN
```

Run the two frozen configurations through the ordinary immutable workflow:

```text
diffeoforge modern-run RECOVERY_DESIGN/modern-euclidean.yaml
diffeoforge modern-run RECOVERY_DESIGN/modern-sobolev.yaml
```

Then create and independently recompute the assessment:

```text
diffeoforge modern-synthetic-recovery-assess RECOVERY_DESIGN \
  RECOVERY_DESIGN-euclidean-run RECOVERY_DESIGN-sobolev-run \
  --output RECOVERY_ASSESSMENT

diffeoforge modern-synthetic-recovery-assessment-verify RECOVERY_ASSESSMENT
```

## Predeclared arm gates

Each arm is assessed independently against the following engineering gates:

- verified immutable Modern workflow;
- explicit optimizer convergence;
- at least 50% pooled vertex-RMSE reduction relative to leaving the generating
  template undeformed;
- pooled reconstruction vertex-error p95 no more than 2% of the generating
  template diagonal; and
- estimated-template vertex-error p95 no more than 2% of that diagonal.

The assessment also reports per-subject and per-family ordered-vertex errors,
the undeformed baseline, and template distance both to the analytic generating
template and to the ordered cohort coordinate mean. Reporting both template
targets makes the atlas-gauge and nonlinear-centering ambiguity explicit.

Sobolev-minus-Euclidean deltas are descriptive. There is deliberately no
predeclared superiority gate and the software selects no winner from this small
benchmark.

## Scientific boundary

The benchmark is smooth, topology-preserving, unitless, and biologically
meaningless. It can expose correspondence-recovery errors and quantify
template-gradient sensitivity under a known construction. It cannot establish
biological validity, generalize to arbitrary anatomical artifacts, replace the
236-subject qualification evidence, or validate downstream biological traits.
