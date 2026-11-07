# Explicit reference-backend server migration

This is an operational checklist for a separately owner-authorized deployment,
not a new desktop transport feature or a claim that every server is supported.
Keep deployment identities, private inputs, checkpoints and receipts outside
the public repository.

## Preserve the scientific contract

Copy the native dependency versions and the composed run-local adapter, and
verify their source hashes in the actual target interpreter. Relocated Python
environments may need an explicit package search path. Import and compilation
checks must use that interpreter, not the server's unrelated system Python.

Retain the ordered complete cohort, input bytes, template, control points,
momenta precision, integration schedule, attachment and deformation settings,
optimizer equations and tolerance. An execution migration does not authorize
decimation, a different engine, additional specimen fitting, a looser tolerance
or a new anatomical acceptance decision. Start with the qualified native
execution topology; independent multi-GPU throughput observations do not prove
ordered full-cohort objective/gradient or global line-search equivalence.

## Optional native multi-GPU contribution workers

`reference_parallel_execution.py` is a standalone Python 3.8-compatible,
explicitly deployed adapter for a Float64 deterministic atlas with frozen
template and control points. It assigns one native contribution worker to each
declared GPU. The native ordered `Pool.map`, per-subject equations, gradient
assembly and single global optimizer remain unchanged. This is full-cohort
evaluation, with one global line-search decision, rather than stochastic updates.

GPU placement must include KeOps reduction device IDs: selecting a Torch CUDA
device alone does not route CPU-hosted kernel-mode tensors. Legacy KeOps compiled
GPU property tables also depend on the number of visible GPUs. Use a separate
cache initialized with the target visible-device count before compilation;
never reuse a cache compiled for one visible GPU on workers targeting four.
The adapter rejects a missing or mismatched cache-topology receipt, unsupported
models, duplicate routing and worker replacement. Deploy it beside the guarded
native entry point without changing the shared runtime installation.

Qualify the actual native interpreter and kernels before private optimization.
Compare serial and parallel full-cohort objective components, all momenta
gradients, native initial step size and the proposed global line-search step.
Do not apply the proposal during qualification. Public 94-subject fixtures with
50 integration points can exercise ordering and global assembly; they do not
establish private-cohort parity, cross-machine reference agreement or an atlas
completion ETA. Keep the separate immutable-origin reference gate before any
private optimizer step, and preserve the original reference on agreement.

Record exact worker identities and GPU assignments and supervise their liveness.
A disappeared or replaced worker must stop the job, not cause an indefinitely
waiting pool or silent recovery. Allow normal pool cleanup after native terminal
metadata. Measure acceleration on the real workload; cold compilation timing and
independent GPU throughput are insufficient evidence of atlas speedup.

## Transfer and stop boundary

Stage a separate private successor and verify every copied input, script and
checkpoint by size and SHA-256 before stopping the source. Preserve a readable
atomic checkpoint with finite parameters and the protected convergence context.
Match the source driver and optimizer by command, working directory and creation
or start time, including the boot identity where available. Target only these
verified processes. Seal the source honestly as interrupted for the requested
handover; do not invent a native numerical stopping reason.

Before target launch, independently confirm that the source optimizer is absent.
A detached, one-shot target driver must prevent duplicates and retain its own
command, directory, start and session receipts. It must not restart after an
error or silently recover a later interruption. A failed staging/import check
is distinct from a failed scientific optimization.

## Cross-machine numerical gate

Load the copied checkpoint through the native API and verify exact restoration
before any optimization step. At startup, evaluate the immutable origin state
with the full ordered cohort and matching arithmetic precision. Compare its
objective with the retained reference using a prospectively declared bound.
On disagreement, stop before optimization. On agreement, restore the current
checkpoint parameters and enter the unchanged native optimizer. Preserve the
original convergence reference; do not replace it with the new machine's value.

The full-cohort check can be expensive. Report it as pending while it runs;
successful imports, a loaded checkpoint and an active process do not establish
numerical equivalence or convergence. Resume still initializes gradients and
line-search step sizes, so uninterrupted trajectory identity is not claimed.

## Owner-requested in-memory pause

An explicit owner pause can retain the existing Linux optimizer in memory with
SIGSTOP. Match the boot, start time, full command, working directory, parent and
selected environment of the driver, optimizer and every contribution worker;
use identity-verified pidfds rather than targeting a PID alone. Stop the driver
first so it cannot advance the chain. Verify all threads stopped, unchanged CPU
counters and logs, a finite protected checkpoint and its separate backup, and
the same process identities over an independent reconnection. Preserve every
earlier pause/resume receipt and mark the current state as owner-paused.

This intended pause is not a native failure or convergence stop. Pause the
monitor and require a new explicit owner instruction before SIGCONT; never
relaunch an optimizer or restore a checkpoint as an automatic substitute. On
verified in-memory continuation, exclude the new pause interval only from
timers that spanned it. A gradient already finished before SIGSTOP must not lose
that interval; an active global line-search evaluation may include it instead.
Process memory survives an SSH disconnect, not a host reboot or process death.

For a separately authorized SIGCONT, reverify the entire stopped process tree,
environments, checkpoint, protected sources, reference context and resources.
Resume contribution workers first, then the existing native parent, record the
running state and measured native pause interval, and resume the driver last.
Preserve earlier pause/resume histories. Independently reconnect to verify the
same identities and active workers before reactivating a quiet monitor with the
current continuation and timing context. This is continuation in memory, not
checkpoint restoration or a new optimizer launch.

## Terminal verification and monitoring

Advance a canonical capped successor only after native return code zero,
consistent terminal metadata and a finite, hash-verified checkpoint with the
same reference context. Full reconstruction/trajectory export remains gated by
the explicit native tolerance stop. Errors, line-search exhaustion, unknown
stops, source changes, duplicate optimizers and insufficient space stop the chain.

At final success, verify the complete subject inventory, every declared retained
trajectory timepoint, file sizes and hashes. Read-only monitoring must follow the
new server chain and distinguish a planned migration from an unexpected failure.
SSH-session independence does not make jobs survive a server reboot. Monitoring
access lifetime and server process lifetime are separate operational concerns.
Numerical convergence, final export, anatomical review and PCA remain separate
states; preserve previously accepted results and analyses.

Change a monitoring interval only on the owner's request, updating the existing
monitor rather than creating a duplicate. Preserve its run identity, destination,
read-only scope and terminal notification rules, then read back the saved schedule.
A longer interval delays discovery of completion or failure; it does not pause,
resume or change the scientific job. Preserve the owner's notification preference,
including a short update after each scheduled check when explicitly requested.

For an owner-requested chat transfer, update the existing monitor's destination
through the app tool and verify the saved target before declaring the transfer
complete. Preserve the exact prompt, interval, active status and other paused
monitors. Keep the original binding active until the update succeeds; do not
create a duplicate or edit scheduler files as a substitute. Transferring the
monitor does not authorize an extra server poll, scientific process action,
resumption of paused maintenance or new fitting work.

## Owner-authorized monitoring access renewal

Renew a monitoring key's expiry only after the owner specifies the new deadline
and timezone. Convert that deadline to UTC explicitly. Preserve the existing
public key, restriction options, other authorized-key entries, file ownership,
permissions and extended attributes. Keep a private, verified backup and guard
an atomic replacement against a concurrent edit; change only the expiry value.

Test a fresh SSH authentication after renewal, then independently verify the
existing scientific process identities, environments and resources. Renewal
does not authorize a restart, a new optimization or broader access. Update the
existing monitor's expiry context while preserving its cadence, notification
rules and read-only scope. Unavailable or expired access means monitoring is
unavailable; it does not establish that the optimizer failed.
