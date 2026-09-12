# Desktop reference-runtime readiness

Status: **launcher-neutral read-only evidence; no reference execution**

Desktop step 2 verifies the exact Deformetrica 4.3 launcher named by one
completed project review. Normal Windows projects use the installer-managed WSL
runtime; same-owner alpha projects may reuse a separately verified existing WSL
runtime. Container and native launchers remain supported configuration routes
for developers and other operating systems.

## Exact binding

The Qt-independent service reads the reviewed configuration bytes, requires
their SHA-256 to match the completed review, validates those bytes in memory,
and extracts the complete launcher mapping. It never substitutes a GUI default.

Launcher-independent observations cover:

- the frozen application runtime and operating system;
- logical CPU count and physical memory;
- project-folder writability and free disk space.

For WSL the service additionally verifies:

- availability of the Windows WSL command;
- presence of the exact configured distribution;
- executability of the exact absolute Linux path; and
- exact Deformetrica version 4.3.0 from a real process probe.

Container diagnostics retain their command, service, and image checks for
developer/CI configurations. Native diagnostics verify the executable and
version. The configuration SHA-256 is checked again after the observations; a
changed or unreadable file discards the result.

## GUI behavior

The check runs outside the Qt event loop. The card shows the reviewed
configuration, hash, project folder, human-readable runtime identity, and every
observed status. A ready result unlocks the supervised reference-execution
step. Advanced approval/status artifacts remain available in internal services
but are not a beginner-facing prerequisite.

The check itself installs, repairs, prepares, and starts nothing. A missing
managed runtime is reported as **repair required**, not as an instruction to
install Docker or manually assemble Python dependencies.

## Non-mutation contract

This service does not modify WSL, a distribution, PATH, the reviewed
configuration, source meshes, run directories, or engine files. Its evidence is
one observation, so the worker re-verifies the configured launcher immediately
before computation.

See [managed Deformetrica reference runtime](MANAGED_REFERENCE_RUNTIME.md) and
[desktop reference prelaunch](REFERENCE_PRELAUNCH.md).
