# Validation strategy

Status: **draft**

The modern backend must not be accepted because its outputs look plausible.
Validation is divided into four layers, each with explicit evidence.

## 1. Software correctness

- schema and path validation tests;
- deterministic file inventories and cryptographic input hashes;
- unit tests for kernels, integration steps, objective components, and I/O;
- finite-difference checks for gradients;
- checkpoint interruption and resume tests;
- clean-environment installation tests;
- migration tests for versioned configuration and manifest schemas.

## 2. Numerical equivalence

The frozen Deformetrica backend is the initial reference, not an unquestioned
ground truth. On small controlled datasets we will compare:

- initial and final objective components;
- objective trajectories under matched optimizer settings;
- reconstructed surfaces and final templates using geometric distances;
- deformation energy and endpoint error;
- control-point trajectories where parameterizations permit comparison;
- repeated CPU runs;
- CPU/GPU differences under declared absolute and relative tolerances.

Momentums and control points may not be uniquely comparable across different
parameterizations. Validation therefore emphasizes observable deformations,
energies, and objective values rather than byte equality of every parameter.

## 3. Scientific robustness

- known synthetic deformations with recoverable endpoints;
- permutation invariance with respect to subject-file ordering;
- template-initialization sensitivity;
- Current versus Varifold behavior under orientation changes;
- mesh-resolution sensitivity;
- parameter sweeps for both kernel widths and noise scale;
- outlier and corrupted-mesh detection;
- preservation of intended topology and absence of invalid geometry.

No numerical acceptance threshold will be chosen after inspecting only the
result it is intended to approve. Thresholds will be justified and versioned.

## 4. Performance and usability

- runtime, peak memory, GPU memory, and disk-output scaling;
- benchmarks across subject count, mesh resolution, and control-point count;
- installation tests on supported desktop and HPC environments;
- time-to-first-valid-run for users without programming experience;
- structured collection of warnings, failures, and recovery actions.

## Reference data policy

Public regression data must be synthetic, public domain, or explicitly licensed
for redistribution. Private manuscript data may be used for local exploratory
testing but must not become a hidden requirement for public verification.
