# Default legacy CPU policy: retained integration evidence

Source: [ab80b503](https://github.com/heinjenny95/DiffeoForge/commit/ab80b503d092d14d41bd2f7790a0e753a41f2944).
Execution: [strict reference CI 34837396916](https://github.com/heinjenny95/DiffeoForge/actions/runs/34837396916).
These are normal `diffeoforge run` executions, without diagnostic mode overrides.

| Runner | Observed CPU | Selected files | Byte-identical to frozen reference |
| --- | --- | --- | --- |
| Ubuntu 22.04 | Intel Xeon Platinum 8573C | 10/10 pass | 10/10 |
| Ubuntu 24.04 | AMD EPYC 7763 | 10/10 pass | 10/10 |

The normal launcher, prepared command and runtime probe all record
`MKL_CBWR=COMPATIBLE`, four threads, CPU mode and backend contract 0.3.
No extra MKL instruction/thread overrides were present. Both maximum and RMS
differences are zero for every selected artifact. Frozen tolerances remain
maximum 1e-6 / RMS 1e-7, and model/data/optimization XML match across hosts.

Each folder retains exactly the ten comparison artifacts, three engine XML
files, original run manifest/checksum, result, lifecycle events and engine log.
These 36 unmodified public files contain no private meshes or pickle checkpoints.
`evidence-sha256.json` records every file's SHA-256 after download. The result's
output inventory and checkpoint fields describe the original full run; only the
bounded files listed here are retained, not an executable/resumable run bundle.
The host-specific runtime receipts identify the independently built images.

Independent verification uses the existing `compare_reference_run` against
`reference/synthetic-v1`, verifies the manifest sidecar, compares prepared/started/
result commands and probe mode, and rechecks every retained file hash. Regression
tests perform these checks without running Deformetrica or changing tolerances.

The [general CI at the same source](https://github.com/heinjenny95/DiffeoForge/actions/runs/34837396899)
passed all ten jobs: 1,483 tests plus 114 skips on each host Python version,
three Modern-engine platform suites and four offscreen desktop platform suites.
A separate local Windows all-tests process aborted with a native access violation
during desktop testing; that observation is not erased by the hosted CI passes.

Scope: one public synthetic cohort, these two CPU models and the frozen legacy
stack. This is not universal hardware, performance or biological qualification,
an installer update, or a resolution of the intermittent native GUI crash.
