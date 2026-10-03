# Deformetrica reference backend

Status: **experimental contract 0.2**

The reference backend makes the existing numerical path inspectable before a
modern replacement is attempted. It is an adapter around an external
Deformetrica 4.3.0 installation, not a fork or redistribution of Deformetrica.
It is currently a research-development tool, not a validated production
pipeline.

## Supported contract

- deterministic atlases of 3D triangular VTK PolyData surfaces;
- Current or Varifold attachment;
- Gradient Ascent optimization;
- CPU execution with explicit KeOps or Torch kernels;
- opt-in Deformetrica `GpuMode.KERNEL` execution in a verified NVIDIA/WSL
  runtime, keeping model tensors on CPU while dispatching KeOps reductions to
  CUDA;
- one native executable or a Windows-to-WSL launcher;
- one offline, read-only Docker launcher using the frozen CPU image;
- Deformetrica version exactly 4.3.0;
- one process, configurable OpenMP thread count, and Float32 precision;
- explicit initial template, control-point spacing, random seed, time
  discretization, optimizer stopping and logging parameters;
- retained flow meshes and a complete output inventory.
- terminal interruption capture and immutable successor resume from an
  inventoried Deformetrica state file.

Full-model CUDA execution, LBFGS, cross-version checkpoint portability,
automatic Docker installation, and scientific production claims are outside
contract 0.2.

## Separation of responsibilities

DiffeoForge validates YAML and geometry, stages immutable inputs, writes the
three XML files, records the exact command and environment, and inventories the
result. Deformetrica performs the numerical optimization. The Python 3.8,
PyTorch 1.6, and PyKeOps 1.4.1 dependencies therefore remain confined to the
external reference environment; the DiffeoForge core itself supports modern
Python.

The launcher is part of the public configuration. A native launcher names a
local executable. On Windows, a WSL launcher names the distribution and the
absolute Linux path to the executable. A container launcher names Docker and a
locally available image. DiffeoForge probes the backend environment and refuses
execution unless it reports Deformetrica 4.3.0. Container runs additionally
record the resolved image ID and repository digests.

For the NVIDIA/WSL route, DiffeoForge additionally executes a small real
Deformetrica KeOps reduction before accepting the runtime. The verified CUDA 12
toolchain is scoped to GCC/G++ 12 for that child process because CUDA 12 rejects
Ubuntu 24.04's default GCC 13 host compiler. The exact GPU, compute capability,
CUDA compiler, host compilers, smoke-test result, and `gpu-mode=kernel` choice
are retained in run provenance. No system-wide compiler default is changed.

## Lifecycle

```bash
diffeoforge validate atlas.yaml
diffeoforge reference-plan atlas.yaml --run-id trial-001
diffeoforge prepare atlas.yaml --run-id trial-001
diffeoforge status runs/trial-001
```

The second command is a versioned, nonmutating exact-byte preview of the third.
It exposes source/staged paths and hashes, effective YAML, all three generated
XML payloads, protected-file byte totals, destination, and command without
creating an output root. See
[the reference preparation plan contract](REFERENCE_PREPARATION_PLAN.md).

At this point inspect `manifest.json`, `config/effective-config.yaml`, and the
three files under `engine/`. Preparation has not started Deformetrica.

```bash
diffeoforge execute runs/trial-001
diffeoforge status runs/trial-001
diffeoforge report runs/trial-001
```

Execution is allowed once. Before launch, DiffeoForge verifies the manifest
checksum, every protected artifact hash, lifecycle state, and the empty output
directory. It then records the backend environment, streams a complete log,
parses objective components into `logs/convergence.csv`, and hashes every
output file.

`Ctrl+C` finalizes partial evidence as `interrupted`. A failed or interrupted
run with an inventoried, hash-matched checkpoint can seed a new immutable
successor through `diffeoforge resume`; the original run is never mutated or
re-executed. See
[checkpoint, interruption, and resume](RESUME_AND_RECOVERY.md) for the recovery
command, provenance files, compatibility boundary, and Pickle security model.

## Local development evidence

On 15 July 2026, contract 0.1 completed a local CPU smoke test with eight
private manuscript meshes and two optimizer iterations. The run used 900
control points, produced 54 output files, and completed in approximately 124
seconds. The logged objective progressed from -51.28 to -49.61 to -47.22.

A second run made previously implicit Deformetrica values explicit. Its
convergence CSV and control points matched the first run. The final template
coordinate difference had maximum absolute magnitude `8.731e-11` and RMS
`1.085e-11`; momenta differed by at most `1.164e-10`. Most output files were
therefore not byte-identical even though their numerical differences were
tiny. Output hashes are integrity evidence, not a scientific equivalence
criterion. Versioned numerical tolerances must be defined independently.

The private meshes are not public reference data and are not part of this
repository.

On 25 July 2026, contract 0.2 executed a complete synthetic Windows-to-WSL
Deformetrica run with `gpu-mode=kernel` on an NVIDIA GeForce RTX 4080 (compute
capability 8.9). DiffeoForge verified CUDA, GCC/G++ 12, and an executable KeOps
kernel before launch; the one-iteration atlas completed with return code 0 and
published a verified result. The first run compiled several KeOps formulas and
therefore took 1 minute 56 seconds; those formula-specific binaries are cached
by PyKeOps for subsequent runs. This is engineering execution evidence, not
CPU/GPU scientific-equivalence evidence.

## Public synthetic reference evidence

On 15 July 2026, two CPU runs processed the CC0 synthetic cohort with the same
contract and a requested maximum of 100 iterations. Both reached the
convergence threshold at iteration 22, improving log-likelihood from -44.07 to
-0.4679. Each complete run produced 61 files totaling 574,096 bytes in about
four seconds. All 60 shared output paths and both convergence CSV files were
byte-identical.

Selected outputs, provenance, hashes, environment versions, and draft numeric
tolerances are published under `reference/synthetic-v1`. The
`compare-reference` command evaluates a new run without requiring exact hashes.
This is same-environment repeatability evidence and an engineering regression
fixture.

The frozen CPU image subsequently rebuilt the environment on a clean
GitHub-hosted Ubuntu 24.04 runner. The container run stopped at iteration 22
and passed all 10 comparisons; every selected artifact was byte-identical to
the reference, with maximum absolute difference 0.0. This establishes the
public container as a working regression environment. Independently justified
tolerances and broader operating-system and CPU coverage remain necessary for
scientific equivalence claims.

## Public interruption and resume evidence

On 15 July 2026, a Windows-to-WSL run of the CC0 synthetic cohort was stopped
with `Ctrl+C` after eight logged objective observations. DiffeoForge finalized
it as `interrupted`, inventoried 61 partial output files, and recorded a
9,392-byte checkpoint. No Deformetrica process remained after terminalization.

An immutable successor copied and hash-verified that checkpoint, recorded its
source manifest, result, inventory, and resume semantics by SHA-256, and invoked
the same Deformetrica 4.3.0 environment. Deformetrica explicitly reported
loading the state file and its first observation retained backend iteration 6
rather than restarting at 0. The successor completed with 104 observations
spanning iterations 6 through 109 in 27.5 seconds. Its result report retained
those true backend iteration numbers and displayed the trajectory-continuity
warning.

The interrupted log had already printed iteration 7 while the last completely
written checkpoint represented iteration 6. This is expected: console output
can be newer than the latest atomic evidence available for resume. A separate
uninterrupted run of the same stress configuration stopped at iteration 101
with log-likelihood -0.1787; the successor stopped at iteration 109 with
-0.1777. This difference is consistent with Deformetrica reinitializing
line-search state and is evidence against claiming exact trajectory continuity.
These runs validate the engineering lifecycle, not scientific equivalence.

## Known limitations

- Docker itself must still be installed and started by the user; the legacy
  environment inside it is automated and hash-locked.
- Absolute source paths in a private manifest may reveal specimen names or
  workstation layout; do not publish run bundles without review.
- Geometry preflight currently targets legacy-file-format VTK PolyData,
  including the VTK 5.1 split OFFSETS/CONNECTIVITY representation.
- The engine emits a PyTorch deprecation warning after the tested run; it does
  not change the successful return code but is preserved in the log.
- Resume is restricted to the identical protected model/configuration and
  Deformetrica 4.3.0 contract; checkpoint portability is not claimed.
- The first GPU run for a new set of KeOps formulas incurs a one-time CUDA
  compilation delay. DiffeoForge reports GPU acceleration only after a real
  kernel has executed, but the atlas-specific formulas may still compile during
  the initial optimization.
- Gradient Ascent checkpoints restore parameters and iteration but not gradient,
  objective baseline, or line-search step sizes; exact trajectory continuity is
  therefore not guaranteed.
- Mesh-output QC visualization, a GUI, and a resource estimator remain future work.
