# Prepare a local correction from a spatially refined saved fit

A qualified saved field can have more original material vertices than the mesh
on which its native optimizer ran. Reusing the old incoming mesh with that finer
endpoint as a protection target previously failed the required connectivity
check. The fit itself remained valid, but no next correction could be prepared.

New preparation detects this mismatch before constructing regional objects.
For a learned field without an existing residual, it selects a bound, nested
original material grid and uses the existing explicit residual contract. The
complete saved field is retained as a fixed prefix; only a new zero field is
prepared for the next local correction. Old control points and momenta remain
unchanged. The UI describes residual initialization rather than a warm restart.

Every old material vertex must remain an identical prefix of the chosen grid.
Equal vertex counts with conflicting connectivity, nonnested coordinates,
changed field parameters or modified geometry fail closed. No endpoint is
interpolated, remeshed or silently truncated to make the array sizes agree.
Ordinary matching warm frames retain their previous behavior.

Where existing residual, automatic and retained comparisons use different grids,
the unchanged fields are independently evaluated on the selected original grid.
Explicit source-grid qualification is bound to its requested field identity and
hash. The original connectivity guard remains in place. New controls follow the
existing residual support and resource limits; fitting is still a separate user
action. Preparation does not approve anatomy or a common-cohort protocol.

Verification includes nested/coarse/fine public geometry, matching warm reuse,
tampered fields/grids, conflicting connectivity and explicit shared-grid field
selection. An isolated replay of the failing production preparation succeeds
without launching an optimizer or writing owner history. A separate native
fixed-zero-field evaluation preserves every starting coordinate and face exactly.
Numerical equations, accuracy gates, iteration caps and saved contracts are
unchanged; a future correction's quality remains subject to normal checks.
