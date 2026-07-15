# ADR 0003: Use a one-directory, CPU-first Windows desktop distribution

- Status: Accepted for the first packaging evidence spike
- Date: 2026-07-15
- Issue: [#22](https://github.com/heinjenny95/DiffeoForge/issues/22)

## Context

DiffeoForge must ultimately serve researchers who do not use Python or a
terminal. The application also needs large Qt/PyTorch native dependencies,
long-running cancellable compute, an independent legacy reference backend, and
scientific provenance that survives packaging.

## Decision

The first desktop target is a Windows x86-64 CPU application using PySide6 for
the GUI, a separate modern-engine worker process, a PyInstaller one-directory
bundle, and an Inno Setup installer. The Deformetrica 4.3 reference environment
remains external and version checked. NVIDIA support is a later, separate
artifact and validation claim.

PyInstaller and the official Nuitka-based `pyside6-deploy` will both receive a
small GUI packaging spike before versions are locked. The one-directory,
worker-process, CPU-first, and external-reference boundaries remain fixed even
if the freeze builder changes after evidence.

## Consequences

- users do not install Python or resolve packages;
- application DLLs remain inspectable and are not extracted on every start;
- the installer can be tested silently on clean Windows VMs;
- CPU and GPU dependency/validation claims cannot be conflated;
- Deformetrica's obsolete dependency closure cannot leak into the GUI process;
- the installed footprint will be large and must be measured openly;
- GUI, freeze, installer, code-signing, SBOM, and clean-machine CI add release
  work before a public executable is credible.

## Rejected for the first release

- a one-file executable that extracts Qt/PyTorch on every launch;
- bundling Deformetrica 4.3 into the desktop runtime;
- downloading Python wheels or engines during first launch;
- a combined CPU/CUDA installer with runtime behavior selected implicitly;
- declaring a developer-built executable usable without clean-machine and
  numerical evidence.
