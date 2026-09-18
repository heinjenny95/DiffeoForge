# Reference production-scale qualification

Status: **production safety gates and replicated 300-subject engineering
qualification passed; final biological-cohort validation remains**

The immediate target is a Deformetrica 4.3 atlas with 300 subjects whose surfaces
have approximately 10,000 faces. DiffeoForge treats a reference workload as
production scale when it combines at least 250 subjects with at least 8,000 faces.
Crossing that threshold does not make the parameters biologically appropriate and
does not by itself prove that the machine can finish the calculation.

## Launch gates

Desktop review measures the exact reviewed cohort and refuses a production-scale
launch when either condition is false:

1. `save_every_n_iterations` is at most 5; and
2. free space on the output filesystem covers two complete working footprints
   (the first immutable run plus one immutable resume successor) and a 2 GiB
   reserve.

The output estimate counts one estimated template and one subject mesh for every
deformation time point plus the final reconstruction, using the largest input mesh
size and a 1.25 serialization factor. It is deliberately a planning reserve, not a
byte-exact prediction. The review shows subject/face counts, projected file count,
estimated output size, required free space, observed free space, and checkpoint
cadence.

Newly generated projects default to a five-iteration checkpoint cadence. Existing
projects retain their saved setting and must be reviewed explicitly; DiffeoForge
does not silently rewrite scientific configurations.

## Recovery contract

The desktop's **Resume interrupted run…** action accepts only terminal
`interrupted` or `failed` Deformetrica reference runs. Discovery is bounded and
read-only. Before enabling execution it verifies:

- the source run manifest and lifecycle;
- source configuration and protected-input hashes;
- terminal result evidence and output inventory; and
- the inventoried checkpoint bytes.

Resume creates a new immutable successor. The source remains outside the write
path. Deformetrica restores parameters and iteration from its checkpoint, but
version 4.3 reinitializes objective, gradient, and line-search state; the continued
optimizer trajectory therefore need not be identical to an uninterrupted one.

The desktop's **Recover after crashâ€¦** action covers power loss and hard parent
termination that leave the latest lifecycle event at `started`. It requires an
explicit stopped-process confirmation, rehashes protected inputs and retained
output, rejects changing files and symbolic output links, and publishes or
reconciles terminal artifacts without restarting Deformetrica. A verified
checkpoint then enters the same immutable-successor path above.

## Evidence already available

- A nine-subject, approximately 10,000-face CPU Coxa atlas completed in
  1,394.469 seconds with 66 convergence rows, 105 result files, and 34,098,261
  result bytes.
- A 54-subject, approximately 1,500-face CUDA validation atlas completed in
  1,036.704 seconds with 57 convergence rows and 1,140 result files. The run
  exercised the RTX 4080 through KeOps CUDA kernels.

These observations validate important parts separately. They do not establish the
combined 300-subject, 10,000-face workload by themselves.

## Combined engineering qualification (11 August 2026)

A deliberately nonbiological cohort replicated the nine private Coxa subject
surfaces into 300 separately named inputs, each with exactly 10,000 faces. The
reviewed test used 252 control points, 10 deformation time points, float32,
Deformetrica 4.3.0, PyKeOps 1.4.1, Torch 1.6.0, WSL Ubuntu, and an RTX 4080 in
verified CUDA-kernel mode.

The production gate passed with 245,377,888,256 free bytes against a
6,349,216,672-byte run-plus-resume requirement. It projected 3,301 VTK files and
1,958,227,473 output bytes. The observed interrupted run contained 3,306 files and
1,114,502,560 bytes, so the byte reserve remained conservative for this cohort.

The fresh run reached two logged optimizer states and was deliberately interrupted
after 278.625 seconds. It finalized cleanly with a 1,940,692-byte inventoried
checkpoint. Resume created a separate immutable successor, restored iteration 1,
reached the configured iteration 3, and completed in 461.938 seconds with 3,306
files and 1,114,472,458 bytes. The source remained terminal `interrupted`; its
manifest, output-inventory, result, and checkpoint hashes still exactly matched the
successor's recorded source evidence.

Five-second whole-machine samples observed at most 1,932 MiB GPU memory during the
fresh run and 1,938 MiB during resume, from a roughly 1,659--1,683 MiB desktop
baseline. Host used memory peaked at 34,942 MiB from a 28,608 MiB fresh-run
baseline on a 130,198 MiB machine. These are coarse whole-machine readings, not
process-exclusive peak-allocation measurements.

For the same 252-control-point geometry on this machine, the observed optimizer and
output cadence supports a rough **three-to-four-hour engineering planning range**
for 150 iterations with a checkpoint every five iterations. It is not an ETA or a
convergence guarantee; control-point count, line search, other system load, storage
speed, and the real cohort can change it materially.

## Remaining final-cohort gate

Only the final real cohort can validate biological parameters, convergence,
registration residuals, deformation plausibility, and PCA stability. A replicated
engineering cohort establishes software scaling and recovery behavior only. Before
the full scientific run, repeat a short pilot on the exact 300 real meshes, confirm
the resulting control-point count and measured resource margin, visually inspect
registrations, and retain the reviewed configuration hash.
