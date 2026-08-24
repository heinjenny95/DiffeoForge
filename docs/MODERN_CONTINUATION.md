# Verified Modern optimizer continuation

Status: **experimental exact complete-cycle successor; not crash recovery**

A Modern atlas that reaches its declared cycle cap without convergence must not
be edited in place or presented as converged. DiffeoForge can instead freeze a
new, prospective successor from that completed run:

```text
diffeoforge modern-continuation-init PARENT_RUN --output PLAN --cycles 10
diffeoforge modern-continuation-verify PLAN
diffeoforge modern-run PLAN/modern-continuation.yaml
diffeoforge modern-continuation-verify-run PLAN SUCCESSOR_RUN
```

The initialization command does not run an optimizer. It first verifies the
parent workflow and nested atlas bundle, then copies and SHA-256 binds:

- the final complete-cycle checkpoint v0.3;
- the final estimated template, control points, and subject momenta;
- retained per-block L-BFGS curvature pairs and the reusable accepted gradient;
- relative-objective baselines and any completed-cycle stop decision;
- the exact effective subject meshes and their deterministic order;
- the model, quality-control, analysis, runtime, and optimizer settings;
- the parent workflow and bundle manifest identities.

The plan also freezes the expected Modern engine implementation revision. A
successor produced by another revision fails lineage verification even if its
human-readable configuration is otherwise identical.

The successor disables a second Procrustes alignment and uses the copied final
state directly. Configuration v0.5 binds the checkpoint and parent effective
configuration. Engine, CPU/float64 runtime, thread count, model, optimizer,
subject order, and numerical initialization must remain identical; only the
new cycle cap and output destination may change.

`modern-continuation-verify-run` proves that the completed successor came from
the frozen configuration, verifies both immutable result layers, checks the
same subject identity/order, and checks that its initial objective matches the
parent's final objective within a relative/absolute tolerance of `1e-12`.

## Scientific boundary

This is sequential optimization, not an independent replicate. It preserves
the parent lineage and avoids silently discarding useful accepted state, but it
does not prove convergence, optimizer equivalence, biological validity, GPU
parity, or production suitability. The parent remains immutable and independently
verifiable. A converged parent is rejected because it has no technical need for
this continuation path.

This mechanism begins only after a completed, verified workflow. It is not a
mid-cycle checkpoint and cannot recover a partially evaluated line-search
candidate or autograd graph. Guarded abandoned-run recovery uses the same exact
committed-cycle state through a separate safety contract.
