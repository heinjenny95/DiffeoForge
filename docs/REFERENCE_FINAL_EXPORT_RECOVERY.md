# Saved-state final-export recovery

An atlas can finish optimization and then fail while writing its complete mesh
trajectories, for example when its output filesystem fills. Ordinary resume in
Deformetrica 4.3 reinitializes objective/gradient state and enters optimization
again. It is therefore not an export-only operation.

`tools/reference_final_export_recovery.py` prepares a separate immutable successor
that restores the saved parameters and invokes the original native final writer,
without running gradient ascent. The original inputs, outputs and checkpoint are
preserved. This is a source support tool; it does not change the installed desktop
or require a new installer version.

## Preconditions and retained evidence

The source must already be terminal `failed` or `interrupted` and pass the standard
resume verification of its manifest, protected inputs, result, inventory and
checkpoint. If a hard failure left its event at `started`, reconcile its metadata
with the existing crash-recovery operation only after verifying that its processes
have stopped. Do not relabel a live job.

The support tool additionally requires:

- a unique, complete checkpoint iteration, read with pickle opcodes without
  deserializing private objects in the frontend;
- a retained native tolerance stop, or iteration-limit evidence with final export
  started, consistent with that checkpoint;
- a retained native flow file to estimate the complete output footprint; and
- free space for a new complete flow export, copied protected inputs, a ten-percent
  output planning margin and a 2 GiB reserve.

Preparation adds a protected declaration binding the source manifest, result,
checkpoint, native stop log and support-tool hash. Its run-local adapter is sealed
with the successor manifest before any execution. Execution rechecks the source
bindings and available output reserve. It never edits an existing run's adapter
or scientific configuration.

## Usage

Use the source environment that supplies `diffeoforge` and the already qualified
reference backend. Check that no conflicting engine is running before execution.

```powershell
python tools/reference_final_export_recovery.py SOURCE_RUN --run-id export-recovery
```

This prepares only and prints the successor path. To prepare and immediately
execute a new successor, add `--execute`. An already prepared, pristine successor
can be executed with `execute_final_export(Path(SUCCESSOR))` from the same module.
Neither operation should be confused with the ordinary optimizer-resume command.

Inside the reference interpreter, the adapter verifies that the loaded checkpoint
hash, iteration and finite parameter arrays exactly match the restored model.
Gradient/objective evaluation is forbidden. The unchanged native writer performs
shooting and writes every configured flow time point, reconstructions and model
outputs. After writing, array shapes, dtypes, byte hashes and iteration must still
match. The inventoried `final-export-state-verification.json` records these
postconditions. Failure does not become a successful anatomical or biological QC.

The export successor has no new optimizer observations. Retained source stop
evidence describes optimization; an empty successor convergence curve must not be
interpreted as a fresh convergence test. The original checkpoint remains the
authoritative saved fit.

Desktop v117 can open such a completed successor for QC and analysis. It verifies
the protected recovery evidence and displays the retained original history without
adding observations to the successor's immutable logs. See
[import contract and limitations](V117_EXPORT_ONLY_RESULT_IMPORT.md).

## Verification and limits

Seven targeted cases and the run lifecycle/recovery suite passed together:
**51 tests**. Tests cover opcode-only inspection, incomplete or ambiguous state,
native stop evidence, complete-flow space planning and rejection before preparation
when space is insufficient.

An actual Deformetrica 4.3.0 CPU engineering test optimized a small two-subject,
three-time-point model, then deliberately failed after its final writer. Export-only
recovery restored iteration 4, produced all nine VTK files byte-identically, kept
saved/model parameter arrays unchanged and left every original source file
unchanged. This establishes the tested recovery path, not scientific acceptance
or byte-identical CUDA serialization on every platform.

Large final exports still take time and disk space. The reserve is a conservative
planning estimate based on retained native serialization, not a quota or a guarantee
against other programs consuming space. This support tool does not add an automatic
desktop recovery action or broaden the existing production-scale launch gate;
both remain separate product work.
