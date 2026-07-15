# Checkpoint, interruption, and resume

Status: **experimental Deformetrica 4.3.0 reference workflow**

DiffeoForge treats interruption as a recorded scientific event, not as permission
to reuse or silently alter an existing run directory. A resumed calculation is
always a new immutable successor run with an explicit link to its source.

## Normal interruption

Pressing `Ctrl+C` while `diffeoforge execute`, `run`, or `resume` streams the
backend log terminates the child process and finalizes the run as `interrupted`.
DiffeoForge records the partial log, convergence rows, output inventory, and
checkpoint metadata in `result.json` and `events.jsonl`. The command exits with
code 130.

Check the terminal state and create a partial result report with:

```powershell
diffeoforge status runs\pilot-001
diffeoforge report runs\pilot-001
```

An interrupted run is terminal. It is never executed a second time.

## Unclean stop recovery

A power loss, operating-system crash, or forcibly killed parent process can leave
the last event as `started` without `result.json`. First verify outside
DiffeoForge that no Deformetrica process is still writing to the directory. Then
finalize the evidence explicitly:

```powershell
diffeoforge recover runs\pilot-001 `
  --reason "workstation lost power" `
  --confirm-process-stopped
```

`recover` never launches Deformetrica. It inventories the files that already
exist and records an `interrupted` terminal result with an unknown return code
and duration. It refuses to run without the confirmation flag, on a lifecycle
other than `started`, or when terminal artifacts already exist.

## Resume as an immutable successor

If the terminal source run contains exactly one inventoried, non-empty checkpoint:

```powershell
diffeoforge resume runs\pilot-001 --run-id pilot-001-resume-01
```

This command atomically prepares a new sibling directory, verifies its immutable
inputs and the checkpoint's recorded integrity, and then executes it. To inspect
the generated successor before committing compute time:

```powershell
diffeoforge resume runs\pilot-001 `
  --run-id pilot-001-resume-01 `
  --prepare-only
diffeoforge execute runs\pilot-001-resume-01
```

The successor contains:

- `resume/resume.json`: versioned provenance linking the source manifest,
  terminal result, output inventory, and checkpoint by SHA-256;
- `resume/source-checkpoint.p`: a protected byte-for-byte copy that is never
  given to the numerical engine for in-place modification;
- `engine/optimization_parameters.xml`: a freshly generated file that names
  `../output/deformetrica-state.p` explicitly;
- `output/deformetrica-state.p`: an execution copy created only after the
  successor passes pre-execution verification.

The source run and protected checkpoint copy remain unchanged. A successor that
is itself interrupted can be the source of another successor, producing an
auditable chain rather than a mutable working directory.

### What Deformetrica 4.3 actually restores

The Gradient Ascent implementation writes only `current_parameters` and
`current_iteration` to the state file. On load it restores those values, then
recomputes the objective and gradient and reinitializes the per-parameter line
search step sizes. Its objective baseline also begins anew in the successor.

Consequently, the first successor observation uses the stored parameters and
iteration, but the optimization steps after it need not reproduce the exact
trajectory that an uninterrupted process would have followed. DiffeoForge
records this as `trajectory_continuity: not_guaranteed` in `resume/resume.json`
and displays a warning. This is a documented Deformetrica 4.3 behavior, not a
claim that the full optimizer state was preserved.

## When resume is unavailable

Deformetrica writes `deformetrica-state.p` at its configured save interval and
at normal completion. If a process stops before the first
`save_every_n_iterations` boundary, no checkpoint may exist. DiffeoForge records
that fact and refuses resume rather than restarting while claiming continuity.

Completed runs are not resumable. Failed or interrupted runs are resumable only
when the checkpoint exists, is represented exactly once in the terminal output
inventory, and still matches the recorded byte count and SHA-256.

## Compatibility and security boundary

`deformetrica-state.p` is a Python Pickle file. Loading an untrusted Pickle can
execute code. DiffeoForge therefore never deserializes, edits, or introspects the
checkpoint. It only copies bytes and verifies size and SHA-256. The file is
loaded exclusively by the configured, version-checked Deformetrica 4.3.0
reference backend during successor execution.

Checkpoint portability across Deformetrica, Python, Torch, PyKeOps, operating
system, precision, model, or configuration versions is not claimed. Resume keeps
the source run's complete protected input/configuration contract and requires
the same frozen backend version. Moving a checkpoint into a different model or
manually editing its XML is outside the supported contract.

Resume preserves the stored model parameters and iteration; it does not preserve
the complete optimizer state or prove convergence, numerical correctness, or
biological validity. The source and every successor should be retained together
when the calculation is used as research evidence.
