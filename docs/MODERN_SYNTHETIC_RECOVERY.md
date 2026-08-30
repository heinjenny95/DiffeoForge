# Modern synthetic analytic recovery

Status: **paired prospective workflow implemented; ordered-point and surface recovery are explicit**

DiffeoForge already generates independent analytic local, global, and mixed
surface deformations. The generator preserves exact ordered vertex
correspondence, but the recovery assessment does not have to assume that
correspondence. The Modern synthetic-recovery workflow binds the benchmark to
two full-atlas configurations:

- Euclidean template gradient;
- Sobolev template gradient with width ratio `1.0`.

Both arms use the same copied benchmark, initial template, control-point
selection, zero momenta, model, optimizer, seed, CPU/float64 runtime, and cycle
cap. The design verifier requires the configurations to be identical except for
the project/output labels and the declared template-gradient variable. A fresh
Euclidean arm keeps the current Engine implementation version and is not
relabeled as a historical implementation.

Every new design freezes one recovery metric before either result exists.
`attachment-native`, the default, selects deterministic symmetric
vertex-to-triangle surface distance for Current or Varifold attachment and
ordered-vertex error for landmark attachment. `--recovery-metric surface` and
`--recovery-metric ordered-vertex` make either choice explicit. Existing v0.1
designs without this field remain verifiable and retain their historical
ordered-vertex interpretation.

Create a known-correspondence benchmark and freeze the paired design before
either result exists:

```text
diffeoforge reference-validation-synthetic-create TEMPLATE.vtk \
  --output SYNTHETIC_BENCHMARK --subjects-per-family 4

diffeoforge modern-synthetic-recovery-init SYNTHETIC_BENCHMARK \
  --output RECOVERY_DESIGN \
  --recovery-metric surface

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

## Predeclared surface-recovery gates

For a Current/Varifold design using the native surface metric, each arm is
assessed independently against:

- verified immutable Modern workflow;
- explicit optimizer convergence;
- at least 50% pooled symmetric-surface RMSE reduction relative to leaving the
  generating template undeformed;
- pooled reconstruction symmetric-surface p95 no more than 2% of the generating
  template diagonal; and
- estimated-template symmetric-surface p95 no more than 2% of that diagonal.

The metric concatenates deterministic vertex-to-triangle distances in both
directions. It is correspondence-independent and insensitive to triangle row
order, winding order, and vertex relabeling that leave the represented surface
unchanged. It is not an exact continuous Hausdorff distance and can still depend
on surface sampling. It evaluates geometric recovery without pretending that
Current/Varifold observes point labels.

## Historical ordered-vertex gates

An explicit ordered-vertex design instead uses the following engineering gates:

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
to exact point correspondence, not gross surface fitting. That mismatch
motivated the new prospective surface-metric design for the landmark-free atlas
rather than interpreting a Current objective as a point-label objective. The
resulting Current surface study is reported below.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1-euclidean-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-design-v0.1-sobolev-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine16-paired-template-gradient-recovery-assessment-v0.1`

## Prospective Engine 1.7 Current surface result

Commit `e0eebfd` added the correspondence-independent metric and froze its gate
contract before the new design or results existed. The subsequent design used
the same 12-subject analytic benchmark, Current attachment, CPU/float64, nine
control points, L-BFGS, and a 100-cycle cap. Its design JSON has SHA-256
`d1f4b0211f01947930c3080be1c38fb0ce6fcf8e34614d4a4d54fdc0bff78b14`.

Both independently verified arms converged and passed every predeclared surface
gate:

- Euclidean converged in 21 cycles, reduced pooled surface RMSE by `77.2019%`,
  and reached reconstruction p95 `0.00355468` of the template diagonal;
- Sobolev converged in 22 cycles, reduced pooled surface RMSE by `77.2113%`,
  and reached reconstruction p95 `0.00355445` of the diagonal;
- generating-template surface p95 was `0.000591918` and `0.000642836` for
  Euclidean and Sobolev, respectively, against the `0.02` ceiling.

Sobolev minus Euclidean reconstruction RMSE and p95 were
`-0.000000759345` and `-0.000000234081` of the diagonal. These negligible
differences support no superiority claim. The independently recomputable
assessment JSON has SHA-256
`de1c23fd16e84cef9aac304d922551c22e9d83191f2296525339349a7cc90ee5`.

Verified evidence directories:

- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-current-surface-recovery-design-v0.1`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-current-surface-recovery-design-v0.1-euclidean-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-current-surface-recovery-design-v0.1-sobolev-run`
- `C:\Users\js7541\Desktop\DiffeoForge Modern Synthetic Recovery 2026-08-27\engine17-paired-current-surface-recovery-assessment-v0.1`

## Scientific boundary

The benchmark is smooth, topology-preserving, unitless, and biologically
meaningless. Depending on the predeclared metric, it can expose point-
correspondence errors or test geometric surface recovery and quantify template-
gradient sensitivity under a known construction. It cannot establish biological
validity, generalize to arbitrary anatomical artifacts, replace the 236-subject
qualification evidence, or validate downstream biological traits.
