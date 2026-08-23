# Modern relative-objective stopping semantics

Status: **implemented and prospectively qualified on the frozen
five-subject full-resolution Weevil fixed-reference screen**

## Corrected interpretation

The frozen fixed-reference workflow previously copied Deformetrica's
`convergence_tolerance` into Modern `gradient_tolerance`. That was semantically
incorrect. The installed Deformetrica 4.3 implementation in
`core/estimators/gradient_ascent.py` applies an accepted step and then tests:

```text
abs(previous_objective - current_objective)
  < convergence_tolerance * abs(initial_objective - current_objective)
```

This is a relative objective-change criterion. It is not an absolute norm of
the full parameter gradient. DiffeoForge's existing reference convergence
documentation independently records the same behavior: Deformetrica accepts
the triggering step before the test but does not print that final state.

## Engine 0.8 configuration

```yaml
optimization:
  gradient_tolerance: 0.0
  relative_objective_tolerance: 0.0001
```

`relative_objective_tolerance` is optional and disabled when absent or `null`.
This preserves every legacy trajectory and termination decision. When enabled,
it must be greater than zero and smaller than one. The test runs only after a
complete optimizer cycle, so multi-block configurations compare like-for-like
cycle endpoints rather than intermediate block updates.

The triggering accepted state remains in the Modern history and checkpoint,
and the result records:

```text
termination_reason: relative_objective_tolerance
converged: true
```

Unlike Deformetrica's terminal log, Modern evidence therefore exposes the
accepted state that triggered the criterion. Gradient norms remain recorded in
every optimizer row. A relative-objective stop is an engineering stop signal;
it does not prove adequate registration, biological validity, or scientific
convergence.

## Fixed-reference mapping and provenance

New fixed-reference designs now:

- bind the source Deformetrica `convergence_tolerance` to
  `relative_objective_tolerance`;
- set absolute `gradient_tolerance` to zero instead of reusing an unrelated
  value;
- record the formula and mapping in the immutable prospective protocol; and
- retain the unchanged external residual, subject-pass, reconstruction, and
  workflow-verification gates.

Completed-run continuation and checkpoint recovery deliberately reject this
criterion for now unless it is already disabled. Exact continuation needs both
the original objective and previous complete-cycle objective in the serialized
lineage. Reinitializing either baseline would change the stop decision. Engine
0.8 fails explicitly until a future checkpoint format stores and verifies both.

Unit and workflow tests establish the exact ratio formula, cycle-boundary
behavior, deterministic termination, schema and bundle provenance, legacy
compatibility, and safe continuation/recovery rejection.

## Prospective real-input result

Before any Engine 0.8 result existed, a five-subject full-resolution Weevil
design froze the Deformetrica-derived tolerance (`0.0001`), L-BFGS/Armijo
optimizer, 150-cycle ceiling, fixed template and control points, subjects, and
all external non-inferiority gates. The run then stopped itself after 84
accepted cycles with:

```text
initial objective:                    -189.78482461065454
final objective:                        -8.926917073610918
termination reason:                     relative_objective_tolerance
cycle 83 relative objective change:      0.00025156877665148848
cycle 84 relative objective change:      0.000069593162405623017
declared tolerance:                      0.0001
```

Thus cycle 83 correctly continued and cycle 84 correctly triggered the
predeclared criterion. The objective was nondecreasing across all 84 accepted
decisions, no optimizer decision failed, and 91 total line-search evaluations
were required. The final gradient norm (`28.4773545271`) and minimum observed
gradient norm (`10.9429228888`) remain diagnostics; neither was repurposed as
the stopping test.

The immutable workflow and a separately published assessment both passed
strict verification. Recomputing every external metric from the bound design
and result produced:

```text
pooled Modern/reference residual ratio:  0.6936240097772872  (maximum 1.2)
subject pass fraction:                    1.0                 (minimum 0.8)
cross-engine reconstruction distance:     0.01896835023041072 (maximum 0.05)
engineering gate:                         pass
```

This qualifies the stopping implementation for this fixed five-subject
engineering screen. It does not qualify a 300-subject production atlas or
establish biological validity.
