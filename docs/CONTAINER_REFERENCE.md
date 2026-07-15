# Frozen Deformetrica CPU container

Status: **experimental reference environment, Linux x86-64 only**

This image isolates the 2020 Deformetrica stack from the modern DiffeoForge
core. It is a reproducibility instrument, not the planned modern engine. The
host runs DiffeoForge on Python 3.11 or newer; Docker runs Deformetrica with
Python 3.8.20 inside the container.

## What is frozen

- official Python 3.8.20 base manifest
  `sha256:d411270700143fa2683cc8264d9fa5d3279fd3b6afff62ae81ea2f9d070e390c`;
- Deformetrica 4.3.0 and its complete minimal Python dependency closure;
- CPU-only PyTorch 1.6.0 and Torchvision 0.7.0 wheels from the official
  PyTorch index;
- PyKeOps 1.4.1 and CMake 3.28.3;
- Debian Bookworm `libgl1`, `libglvnd0`, and `libglx0`, each at version
  1.6.0-1, required by Deformetrica's unconditional Qt import;
- SHA-256 for every selected Python wheel or source archive.

The lock was derived from a fresh environment, not from the notebook
environment as a whole. Jupyter, pandas, seaborn, and other unrelated packages
are absent. The exact files are in `container/`.

This is a source- and artifact-pinned build recipe. It does not yet claim that
independent builds have the same container-image digest. DiffeoForge records
the actual local image ID and any repository digests in every run result.

## Build once

Docker Desktop or another Docker-compatible engine must be running. From the
repository root:

```bash
docker build --platform linux/amd64 \
  --file container/Dockerfile \
  --tag diffeoforge-deformetrica:4.3.0-cpu .
```

The build downloads only hash-accepted Python artifacts. It is intentionally
large because VTK, Qt, and the compiler toolchain are requirements of the
legacy distribution. On ARM computers Docker must emulate `linux/amd64`.

## Run the public acceptance case

Install the current DiffeoForge core in a modern environment, then run:

```bash
diffeoforge run examples/minimal-atlas-container.yaml --run-id container-smoke
diffeoforge compare-reference \
  examples/runs/container-smoke reference/synthetic-v1
```

The first execution compiles formula-specific PyKeOps C++ kernels in a
temporary in-memory filesystem and is therefore slower. The actual atlas runs
inside a read-only container without network access. Only the immutable run
directory is mounted read-write at `/work`. On Linux, the launcher maps the
host user and group so output files are not owned by root.

The acceptance command must report 10 of 10 artifacts passed. The published
GitHub Actions workflow repeats the build, atlas execution, and numerical
comparison on a clean runner.

## Use it for another dataset

Copy `examples/minimal-atlas-container.yaml`, then change the input directory,
template, subject pattern, output directory, and scientifically chosen model
parameters. Keep the container launcher block unchanged. DiffeoForge stages
the source meshes into a self-contained run directory before Docker starts, so
the container never needs access to the original data directory.

Preparation and execution remain separate when desired:

```bash
diffeoforge validate my-atlas.yaml
diffeoforge prepare my-atlas.yaml --run-id trial-001
diffeoforge execute path/to/runs/trial-001
```

Docker never pulls an image implicitly during execution (`--pull=never`). A
missing image therefore fails before computation rather than silently changing
the environment.

## Scientific and security boundary

The numerical reference thresholds remain engineering regression gates, not
biological equivalence criteria. The image intentionally preserves unsupported
legacy software and should process only trusted research meshes. Network
isolation and a read-only root reduce exposure but do not turn old dependencies
into maintained software. The modern-engine milestone exists to remove this
legacy stack from future production use.
