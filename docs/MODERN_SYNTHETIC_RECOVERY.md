# Modern synthetic known-correspondence recovery

Status: **paired prospective workflow implemented; first 12-subject evidence run completed**

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
  --output RECOVERY_DESIGN --attachment-type current

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

## First prospective result, 27 August 2026

The first design used four subjects in each analytic family (12 total), Engine
1.6, CPU/float64, nine control points, L-BFGS, and a 100-cycle cap. The design
and gates above were committed before the dataset, runs, or assessment existed.
Both immutable workflows and the independently recomputed assessment verify.

Both arms converged by the declared relative-objective tolerance: Euclidean in
21 cycles and Sobolev in 22. Both preserved the generating template accurately:
template vertex-error p95 was `0.000613367` and `0.000666700` of the template
diagonal respectively, comfortably inside the `0.02` gate.

Both arms nevertheless failed the predeclared exact-correspondence recovery
gates:

- Euclidean pooled vertex RMSE fell by only `8.6003%` from the undeformed
  baseline and its reconstruction p95 was `0.0334266` of the diagonal;
- Sobolev pooled vertex RMSE fell by `8.4347%` and its reconstruction p95 was
  `0.0335374` of the diagonal;
- the required reduction was at least `50%` and the p95 ceiling was `0.02`.

The paired differences were small: Sobolev minus Euclidean reconstruction RMSE
and p95 were `+0.000028985` and `+0.000110774` of the diagonal. This supports no
superiority claim.

This negative gate result is informative. The configured Current attachment
compares oriented surfaces and does not observe vertex labels. A post-result,
non-gating diagnostic using deterministic symmetric vertex-to-triangle distance
showed that both arms did recover surface geometry well: pooled surface RMSE
improved by `77.2019%` (Euclidean) and `77.2113%` (Sobolev), with surface p95 of
approximately `0.00355` of the diagonal. Thus the observed failure is specific
to exact point correspondence, not gross surface fitting. The next diagnostic
must isolate fixed-template registration. It also motivated the separate,
strictly opt-in Engine 1.7
[ordered-landmark attachment](MODERN_LANDMARK_ATTACHMENT.md), rather than
silently interpreting a Current objective as a point-label objective. Any
landmark-mode recovery run is a new prospective experiment, not a reinterpretation
of this completed result.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1-euclidean-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1-sobolev-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-assessment-v0.1`

## Engine 1.7 ordered-landmark successor

After the Current result exposed the intended surface/point distinction,
Engine 1.7 added an explicit ordered-landmark attachment and froze a new design
before its results existed. Both 12-subject full-atlas arms passed all original
exact-correspondence gates. Euclidean and Sobolev reduced pooled vertex RMSE by
`82.1042%` and `82.1388%`; reconstruction p95 was `0.00660297` and
`0.00656287` of the diagonal. Both template p95 values were below `0.00590`.

This successor validates the opt-in point-aware path on analytic known
correspondence. It does not retroactively turn the Current result into a pass,
show that empirical input vertices are homologous, or establish a meaningful
Sobolev advantage. Full details and evidence paths are in
[Modern ordered-landmark attachment](MODERN_LANDMARK_ATTACHMENT.md).

## Scientific boundary

The benchmark is smooth, topology-preserving, unitless, and biologically
meaningless. It can expose correspondence-recovery errors and quantify
template-gradient sensitivity under a known construction. It cannot establish
biological validity, generalize to arbitrary anatomical artifacts, replace the
236-subject qualification evidence, or validate downstream biological traits.
