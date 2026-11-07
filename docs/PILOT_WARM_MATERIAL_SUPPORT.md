# Check local control support before another warm test

An existing local field can have dense controls around one projection and only
coarse controls near another newly selected part. Reusing its coefficients on
that same basis can then spend a trial with little useful local movement.

New preparation checks the selected material against the existing local basis's
declared coverage bound. Selection follows the current numerical surface and
excludes fixed-incident triangles. Distances use the selected material's incoming
coordinates and the matching initial controls; output coordinates are not mixed
with initial controls. The check verifies identities and changes no field.

If a declared local warm basis misses that material, preparation keeps its whole
saved deformation as a prefix and uses the existing supported zero-residual route.
The movement scale, weights, native budgets and preservation bounds remain.
Explicit Retain keeps its own field reference, with matching material frames.
The recorded recipe explains the basis response. No controls are inserted into a
nonzero field in place, no optimizer memory is restored and no failed result is
silently approved. Legacy/undeclared, shape-guide and same-objective extension
contracts retain their previous path.

Quality provenance also retains the complete instruction list, including fixed
and shape-preservation marks. Surface measurement scope is recorded separately.
Previously, a valid protected result could fail the next-stage scope comparison
because its quality row listed only problem surfaces while feedback included a
Retain mark. Changed instructions still invalidate reuse; unchanged problem
surfaces retain their cached capture measurements.

Verification: the preparation/control suite passed 88 cases and the overlapping
instruction-scope/recovery suite passed 69 cases, with eight new cases overall.
Tests cover incoming/output frame separation, identity, legacy/guide skips, real
prepare-only conversion and preservation of parent files, full fixed-instruction
scope, changed-mark rejection and capture reuse. Lint passes. A new independent
private residual trial improved the previously unsupported part and passed full
field/time/spatial/Retain/outside/intersection checks without changing owner runs.
This is separate from anatomical approval or a universal speed guarantee.
Installed runtime remains dev175 pending verified delivery.
