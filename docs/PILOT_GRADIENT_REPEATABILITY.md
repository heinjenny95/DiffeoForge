# Reproducible surface gradients in new regional trials

The pinned Torch 1.6 CPU backward for advanced vertex indexing can accumulate
triangle contributions in different orders when several threads are active.
Deformetrica's native SurfaceMesh uses this indexing to retrieve triangle
vertices. The resulting gradient can vary at an identical parameter vector even
when the objective is exactly unchanged. The strict finite-accepted guard
correctly rejects this inconsistent pair; raising the iteration budget is not a
repair.

dev166 stages a protected, versioned `cpu_surface_gather.py` adapter for newly
prepared guarded regional trials. CPU triangle retrieval uses equivalent
`torch.index_select` operations. Centers and normals retain their exact original
forward operations and values; gradients use reproducible accumulation. The
normal kernel-GPU execution path also uses these CPU surface operations. Non-CPU
surface retrieval is delegated to the original native method.

The adapter binds its declaration, source bytes and the exact qualified original
native surface module. It is part of the immutable run context. Existing prepared
and completed runs retain their recorded engine and metadata; no installed native
library is edited. New trials retain the original precision, objective, control
basis, integration, cap, tolerance and thread allowance. No gradient cache,
replacement gradient, clipping or relaxed comparison conceals a discrepancy.

## Verification

A synthetic pinned-runtime CPU test varied in 19 of 19 repeated gradients with
advanced indexing and four threads; the equivalent index-select path had zero
differences. Both were reproducible with one thread. Generic source tests also
check exact forward geometry, repeated derivatives, finite differences, legacy
rendering, schema binding and the untouched non-CPU delegation.

Separate copies of real inputs and an immutable saved parameter point reproduced
the violation in both CPU and normal kernel-GPU execution. The correction passed
six interleaved repeat pairs bit-for-bit in both modes. The actual generated,
protected adapter passed the same GPU test without a private method replacement.
A new normal fit completed, exported and loaded its bound field; the ordinary
prepare/supervisor/intermediate-finish/export path also passed on a tiny synthetic
fixture. Private values, meshes and outputs remain outside the public repository.

These checks establish the scoped numerical repair, not anatomical suitability,
an arbitrary speedup or adequate fit on every projection. The alternative-method
experiment remains closed. The ten-active-minute review policy is unchanged.

## Related workflow repairs

Transitional cohort staging previously removed `regional_fit` and its guard while
retaining `pilot_review`, causing the configuration schema to reject the next
step. The complete regional runtime contract is now cleared together at these
boundaries and reintroduced only for the prepared singleton. A real failed
transition was reproduced and validated in memory without changing its file.

Explicit native L-BFGS relative-objective/projected-gradient tolerance messages
now have a distinct `lbfgs_tolerance` interpretation. A failure or explicit review
stop takes precedence. This recognizes a native numerical stop; geometry and
human suitability checks remain separate. Backend duration labels explicitly
include review waits rather than presenting that whole duration as active fitting.

The qualified source is dev166. Installation and exact-package verification are
recorded separately; the last verified installed runtime remains dev165 until
the delivery record supersedes it.
