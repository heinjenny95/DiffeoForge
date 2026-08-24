# Exact complete-cycle optimizer continuation

Status: **implemented through Modern Engine 1.4; exact at committed cycle boundaries**

Engine 0.9 extended the private Modern checkpoint format from parameter-only
state to exact single-block optimizer state. Engine 1.2 checkpoint v0.3 extends
that contract to separate histories for every configured optimizer block. It
stores and verifies:

- estimated template, control points, and subject-ordered momenta;
- the next accepted starter step;
- the original and current complete-cycle objective baselines;
- the reusable accepted gradient;
- every retained L-BFGS curvature pair in deterministic per-block order; and
- a convergence decision made by the completed cycle, if one was triggered.

Engine 1.3 additionally binds `momenta_updates_per_cycle`; historical absence
means one, while a multi-rate successor must retain the exact expanded schedule.
Engine 1.4 also binds `subject_batch_size` and `subject_batch_workers` so a
checkpoint cannot cross into a different floating-point grouping or execution
schedule. Historical absence means no finite batching and one worker.

Optimizer tensors use a non-executable, little-endian float64 binary store with
explicit names, shapes, byte offsets, byte lengths, and SHA-256 evidence. No
pickle or executable deserializer is used. Verification rejects non-finite
values, inconsistent shapes, invalid curvature, missing bytes, trailing bytes,
or any manifest/hash mismatch.

Configuration v0.5 can bind one verified exact-state checkpoint plus the exact parent
effective configuration as `optimization.resume_state`. Preflight requires the
same Engine implementation, CPU/float64 runtime, thread count, model,
optimizer settings, subject identity/order, template, control points, and
momenta. Only the new cycle cap and immutable output destination may differ.

This makes both completed-run continuation and guarded abandoned-run recovery
mathematically continuous for single- or multi-block L-BFGS,
previous-accepted step reuse, and
relative-objective stopping. If the last committed cycle already triggered a
stopping criterion, the successor publishes that converged state with zero
additional cycles rather than taking an extra step.

New configurations checkpoint every five complete cycles and retain only the
latest verified checkpoint. The terminal cycle is always retained. This bounds
checkpoint disk growth while limiting hard-crash rollback to at most four
completed cycles. Both cadence and retention are explicit configuration and
immutable workflow evidence; legacy configurations keep every cycle.

## Evidence

The test contract compares uninterrupted single-, multi-block, and multi-rate L-BFGS
trajectories with split trajectories. After checkpoint serialization, plan
verification, deserialization, and a public successor workflow, the final
objective and canonical state are exactly equal. Core tests also exercise
Strong-Wolfe L-BFGS, terminal relative-objective decisions, block-specific tensor
shape validation, positive curvature, and legacy v0.2 loading.

## Boundary

This is exact only at a fully committed cycle boundary. A partial cycle,
line-search trial, autograd graph, process state, elapsed time, and log history
after the last checkpoint are deliberately discarded. Recovery never resumes a
live process, modifies the parent, overwrites a destination, or runs compute
automatically. Checkpoint v0.1 remains verifiable as legacy evidence but is not
sufficient for exact stateful continuation. Checkpoint v0.2 remains loadable for
its historical exact single-block contract, but engine identity prevents silent
cross-version continuation.

Exact numerical continuation does not establish registration quality,
biological validity, convergence adequacy, GPU parity, or production readiness.
