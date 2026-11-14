# Legacy CPU launch policy (backend contract 0.3)

New Deformetrica reference CPU commands explicitly set `MKL_CBWR=COMPATIBLE`.
The setting is process-scoped, not installed into the user's global environment.
It applies to native, WSL and container atlas estimation and CPU Shooting.
GPU launch settings and the Modern engine are unchanged. Model XML, optimizer
settings, frozen dependencies, reference bytes and comparison tolerances are unchanged.

## Evidence and recording

The [retained full-atlas pair](../reference/reference-cpu-full-pair-v1/README.md)
supports this decision on one public synthetic cohort: Intel Xeon 8573C AUTO
passed 8/10 files twice, while COMPATIBLE passed all 10 byte-identically twice.
AMD EPYC 7763 passed both modes twice. COMPATIBLE outputs matched across hosts.

The exact setting is in `manifest.json` → `command_preview.environment`, then
the started event and `result.json` → `command.environment`. The CPU environment
probe receives the same process settings, including the configured thread count,
inside the actual native/WSL/container runtime. Its allowlisted numerical-environment
receipt and CPU model are recorded alongside the command. PATH-resolved native
executables without adjacent Python retain an explicit `not_available` probe
status; a requested setting is not a verified runtime receipt.

Other inherited MKL overrides are not silently removed. Their recorded values
must be considered when interpreting results; non-default overrides, other BLAS
implementations, processor families and biological datasets are not qualified by
the public pair. No universal byte-identity, speed or biological-validity claim
follows from setting this variable.

## Existing projects and checkpoints

Historical manifests (contracts 0.1/0.2) remain readable; completed results are
not rewritten. A prepared CPU run without the explicit COMPATIBLE command record
cannot start under the new policy. Prepare and review a fresh run, or use its
original software/environment. A failed/interrupted source without a COMPATIBLE
execution record cannot supply a checkpoint to the new launcher. The guard runs
before engine launch or successor creation and leaves source evidence untouched.
Eligible new-policy checkpoints can still create immutable successors.

CPU Shooting is a new derived operation with its own recorded command, not a
continuation of an old optimizer checkpoint. Generating it from older results
does not retroactively qualify their original environment or change their files.

## Verification boundary

Launcher/probe, manifest, resume and diagnostic tests cover the policy and GPU
exclusion. The diagnostic explicitly replaces the product default so its AUTO
observations cannot accidentally execute COMPATIBLE through duplicate Docker flags.
The normal strict reference workflow now runs on Ubuntu 22.04 and 24.04 with no
mode override: actual CPU identity and all ten selected artifacts are retained
for independent readback. Runner labels alone do not establish CPU coverage.
The [retained post-change executions](../reference/reference-cpu-policy-v1/README.md)
passed 10/10 byte-identically on observed Intel Xeon 8573C and AMD EPYC 7763.
Prepared/started/result commands and the actual runtime probe agree on the mode.
All ten general CI jobs passed at the implementation commit; 127 focused local
tests passed with two Windows symlink-permission skips. The additional local
all-tests process hit a native desktop access violation, retained as an open
GUI investigation rather than a clean full-suite claim. No installer or release
is implied.
