# Modern complete-cycle checkpoints

Status: **implemented private state and guarded successor-recovery contract**

Every newly started Modern workflow writes an immutable checkpoint after the
last parameter block of each fully completed optimizer cycle. A checkpoint
contains:

- the detached estimated template as VTK;
- canonical control points and subject-ordered momenta;
- the complete committed optimizer record;
- the next starter step for every configured parameter block;
- hashes of the source/effective configuration and every effective input mesh;
- the Modern engine implementation revision;
- a complete artifact inventory and manifest sidecar.

Checkpoint publication uses a fresh temporary directory and atomic rename. A
callback receives cloned tensors, so checkpoint code cannot mutate the active
optimizer. Failed line-search attempts and partially completed multi-block
cycles are never checkpointed.

On normal completion, the workflow manifest inventories every checkpoint,
requires the exact cycle sequence, verifies each nested manifest and input
binding, and requires the last checkpoint objective components to equal the
final atlas bundle. Older workflows without checkpoint records remain readable.

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
a new immutable prospective plan, and writes a separate non-overwriting v0.4
successor configuration. The source directory is never changed. See
[guarded Modern checkpoint recovery](MODERN_CHECKPOINT_RECOVERY.md).

Recovery deliberately discards a partial cycle and the transient in-memory
autograd/line-search graph. It restores the committed template, control points,
subject-ordered momenta, and next starter steps. The successor is a sequential
run, not an independent replicate or a claim that the interrupted computation
converged. This is guarded complete-cycle recovery, not transparent process
resume.
