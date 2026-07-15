# Deformetrica reference backend

Status: **experimental contract 0.1**

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
- one native executable or a Windows-to-WSL launcher;
- Deformetrica version exactly 4.3.0;
- one process, configurable OpenMP thread count, and Float32 precision;
- explicit initial template, control-point spacing, random seed, time
  discretization, optimizer stopping and logging parameters;
- retained flow meshes and a complete output inventory.

GPU execution, LBFGS, resume, automatic engine installation, containers, and
scientific production claims are outside contract 0.1.

## Separation of responsibilities

DiffeoForge validates YAML and geometry, stages immutable inputs, writes the
three XML files, records the exact command and environment, and inventories the
result. Deformetrica performs the numerical optimization. The Python 3.8,
PyTorch 1.6, and PyKeOps 1.4.1 dependencies therefore remain confined to the
external reference environment; the DiffeoForge core itself supports modern
Python.

The launcher is part of the public configuration. A native launcher names a
local executable. On Windows, a WSL launcher names the distribution and the
absolute Linux path to the executable. DiffeoForge probes the adjacent Python
environment and refuses execution unless it reports Deformetrica 4.3.0.

## Lifecycle

```bash
diffeoforge validate atlas.yaml
diffeoforge prepare atlas.yaml --run-id trial-001
diffeoforge status runs/trial-001
```

At this point inspect `manifest.json`, `config/effective-config.yaml`, and the
three files under `engine/`. Preparation has not started Deformetrica.

```bash
diffeoforge execute runs/trial-001
diffeoforge status runs/trial-001
```

Execution is allowed once. Before launch, DiffeoForge verifies the manifest
checksum, every protected artifact hash, lifecycle state, and the empty output
directory. It then records the backend environment, streams a complete log,
parses objective components into `logs/convergence.csv`, and hashes every
output file.

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
fixture; cross-platform equivalence still requires a pinned execution
environment and independently justified tolerances.

## Known limitations

- Environment creation is not automated yet.
- Absolute source paths in a private manifest may reveal specimen names or
  workstation layout; do not publish run bundles without review.
- Geometry preflight currently targets legacy-file-format VTK PolyData,
  including the VTK 5.1 split OFFSETS/CONNECTIVITY representation.
- The engine emits a PyTorch deprecation warning after the tested run; it does
  not change the successful return code but is preserved in the log.
- Run interruption and resume are not implemented.
- A convergence plot, mesh QC report, GUI, and resource estimator remain
  future work.
