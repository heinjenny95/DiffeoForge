# Desktop reference-environment readiness

Status: **read-only environment evidence; no reference execution**

Desktop step 2 can inspect the external Deformetrica 4.3 container route named
by one completed reference-project review. This makes the legacy dependency
boundary visible without importing or bundling Deformetrica's Python 3.8 stack
in the desktop application.

## Exact binding

The Qt-independent service accepts a `ProjectReviewResult` for the reference
engine. It reads the configuration bytes once, requires their SHA-256 to equal
the completed review, parses and validates those bytes in memory, and extracts
the declared container engine and image. It does not substitute GUI defaults.

The existing `run_doctor` service then observes:

- host Python and operating system;
- logical CPU count and physical memory;
- project-directory writability and free disk space;
- presence of the configured container command;
- container-service readiness; and
- local availability of the configured immutable reference-image name.

The configuration SHA-256 is checked again after those commands finish. A
changed or unreadable file discards the entire diagnostic result. Native and
WSL reference launchers remain explicit unsupported desktop-diagnostic routes
in this slice; the generated desktop reference project uses the reviewed
container contract.

## GUI behavior

The check runs in a Qt thread-pool task, so container-service timeouts do not
freeze the event loop. The card shows the exact configuration, review hash,
project directory, engine, image, and every doctor's raw status, label,
summary, and optional guidance. Refresh starts a new read-only observation.

A ready report does not enable the reference compute button. Preparing a run,
supervising Deformetrica and its descendants, cancellation, parent-death
containment, checkpoint/resume, abandoned-run recovery, and verified result
handoff remain a separate engineering gate.

## Non-mutation contract

This service does not:

- install or configure a container engine;
- build, pull, delete, or start an image;
- modify PATH, Docker settings, or the reviewed configuration;
- create a reference run directory or XML files;
- launch, resume, recover, or terminate Deformetrica; or
- claim scientific validity, parameter suitability, runtime, or memory.

Its result is observational evidence at one moment. Container state may change
afterward, so a future reference supervisor must perform its own immediate
pre-launch checks rather than trusting this display as authorization.
