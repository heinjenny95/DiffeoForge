# Modern complete-cycle checkpoints

Status: **implemented private state and guarded successor-recovery contract**

Every newly started Modern workflow writes an immutable checkpoint after the
last parameter block of a configured fully completed optimizer cycle. Newly
generated configurations use:

```yaml
optimization:
  checkpoint_interval_cycles: 5
  checkpoint_retention: latest
```

The terminal cycle is always checkpointed, even when it is not divisible by
five. `latest` writes and verifies the new checkpoint before atomically
retiring the preceding private checkpoint, so retained optimizer state is
bounded by one checkpoint instead of growing once per cycle. Legacy
configurations without these fields preserve the original `1`/`all` behavior.
Choosing `all` is explicit forensic retention and can consume substantial disk
space for L-BFGS cohort state.

A checkpoint contains:

- the detached estimated template as VTK;
- canonical control points and subject-ordered momenta;
- the complete committed optimizer record;
- the next starter step for every configured parameter block;
- original/current objective baselines and a completed-cycle stop decision;
- the reusable accepted gradient and retained per-block L-BFGS curvature pairs;
- hashes of the source/effective configuration and every effective input mesh;
- the Modern engine implementation revision;
- the declared Momenta-update count per complete optimizer cycle when present;
- a complete artifact inventory and manifest sidecar.

Checkpoint publication uses a fresh temporary directory and atomic rename. A
callback receives cloned tensors, so checkpoint code cannot mutate the active
optimizer. Failed line-search attempts and partially completed multi-block
cycles are never checkpointed.

On normal completion, the workflow manifest records the effective persistence
policy, inventories every retained checkpoint, requires its exact scheduled
cycle sequence, verifies each nested manifest and input binding, and requires
the last checkpoint objective components to equal the final atlas bundle.
Older workflows without a policy retain contiguous-cycle verification.

If the process or machine dies, the private run directory and its last complete
checkpoint can remain for inspection because normal exception cleanup did not
run. A handled error or cooperative cancellation still removes the unpublished
private workflow as before. The currently running Weevil continuation was
started from the earlier implementation and therefore cannot acquire checkpoints
retroactively.

These files are recovery ingredients, not automatic recovery authorization.
`modern-checkpoint-recovery-init` accepts only a private directory that strict
read-only lease discovery classifies as `abandoned`. It verifies the contiguous
checkpoint sequence, embeds the latest complete cycle and every bound input in
a new immutable prospective plan, and writes a separate non-overwriting v0.5
successor configuration. The source directory is never changed. See
[guarded Modern checkpoint recovery](MODERN_CHECKPOINT_RECOVERY.md).

Recovery deliberately discards a partial cycle and the transient in-memory
autograd/line-search graph. Checkpoint v0.3 restores the committed parameters,
next steps, objective baselines, reusable gradient, and every separate block
L-BFGS history exactly. Checkpoint v0.2 remains verifiable and exactly loadable
for its historical single-block contract; checkpoint v0.1 remains readable but
cannot authorize a stateful successor. Engine identity remains bound, so an old
checkpoint is never silently resumed under new optimizer semantics.
Historical bindings without `momenta_updates_per_cycle` mean one. Engine 1.3
binds the value explicitly, so a multi-rate checkpoint cannot be resumed with a
different schedule.
Engine 1.4 additionally binds `subject_batch_size` and
`subject_batch_workers`. Historical absence means an unbatched one-worker path;
new continuation or recovery must retain both values exactly.
Engine 1.5 permits live state tensors on CUDA but copies every published tensor
to canonical CPU float64/int64 form before writing VTK, CSV, or the
non-executable optimizer tensor store. Resume moves the verified CPU state back
to the exactly declared runtime device; changing device across a continuation
boundary remains forbidden.
The successor is a sequential run, not an independent replicate or a claim
that the interrupted computation converged. This is guarded exact
complete-cycle recovery, not transparent process resume.
