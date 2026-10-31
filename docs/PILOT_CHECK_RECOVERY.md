# Cancellable saved-fit checks

Native fitting and its subsequent surface/field checks are separate work. A
normally completed fit is retained when the researcher cancels its checks.
Isolated MeshLab filters now observe the operation's cancellation request while
waiting, with the existing timeout and owned-process cleanup still in effect.
Fixed-field process waits also wake promptly on completion and check cancellation
between short waits; the visible progress cadence remains one second.

The guided pilot offers **Resume checks on saved fit · no new fitting** for a
recorded post-fit interruption. Before reuse, the runner verifies the configuration,
run identity, manifest, result, output inventory and event history, then performs
the normal artifact checks. Reuse creates no optimizer controller. Changed,
missing, failed or unbound evidence cannot trigger this route. Unknown crashes
and interrupted optimizers are not automatically restored. The current route
requires an identical source configuration; it does not infer checkpoint lineage.

Resumed checking time is reported separately from the saved native runtime.
Regional checking uses one elapsed clock across its internal batches. Failed
numerical gates remain visible even when fitting reached tolerance or a visual
suitability decision exists. Checks neither approve anatomy nor authorize a
shared-cohort model.

The regional scope banner uses the same A/B/C order as the point editor, including
interleaved retain marks. It names the active improvement and protection marks,
and marks waiting for a later attempt. This is an explanation of the prepared
objective, not a change to those instructions or a guarantee of a suitable fit.

Conforming original-source subdivision uses vectorized connectivity assembly,
preserving the previous face, edge, vertex, child and parent order exactly. The
source grid, limits, native equations, tolerance and acceptance gates are unchanged.
Historical edge-pattern tests and independent saved-grid replay check exact
connectivity and coordinates. This removes Python bookkeeping; it is not a
claim of a faster optimizer or generally successful projection geometry.
