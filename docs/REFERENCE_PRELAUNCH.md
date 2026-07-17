# Desktop reference prelaunch contract

Status: **read-only future-supervisor input; no reference execution**

The reference prelaunch contract turns a completed parameter review and one
matching ready environment observation into a versioned, machine-validatable
request. It prevents a future desktop supervisor from rebuilding critical
values from mutable widgets or implicit defaults.

## Exact binding

`desktop-reference-launch-request-v0.1.json` records:

- a bounded request identifier;
- the absolute configuration path and reviewed SHA-256;
- the Deformetrica reference engine identity;
- the configured container command and immutable image name;
- an explicit normalized run identifier; and
- the exact absolute destination resolved from the configuration.

Construction accepts only a Deformetrica reference review and a ready
`DesktopReferenceReadiness` object with the same path, hash, workspace, engine,
and image. It reads and validates the exact configuration bytes, resolves the
output path through the shared core, and refuses an existing destination.

## Repeatable verification

The immutable request can be serialized and reconstructed through its JSON
Schema. `verify_launch_inputs()` re-reads the bytes, checks SHA-256 before and
after parsing, revalidates the reference configuration, compares launcher
settings and output resolution, and again requires a nonexistent destination.

This check is deliberately repeatable. A future worker must invoke it inside
the contained child process immediately before preparation. The earlier doctor
report and this request do not make changing external state safe by themselves.

## Non-mutation and interpretation boundary

Building, serializing, parsing, or verifying this request does not:

- create an output root, run directory, XML file, log, or manifest;
- install, pull, build, start, stop, or inspect a container beyond the separate
  readiness observation already supplied;
- launch Deformetrica or enable the reference compute button;
- implement cancellation, parent-death containment, recovery, or resume; or
- predict runtime, memory, convergence, parameter suitability, or biological
  validity.

The contract is one prerequisite for reference-process supervision. It is not
launch authorization and not scientific validation.
