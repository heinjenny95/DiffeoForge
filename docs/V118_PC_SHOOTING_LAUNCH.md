# v118 — PC Shooting launch for long project paths

PC shape generation could fail before Deformetrica started with Windows error
267 when an immutable saved-run hierarchy made its temporary working directory
longer than Windows process creation supports. WSL already receives the correct
directory through `wsl.exe --cd`; the redundant Windows subprocess `cwd` was the
failure point.

Shooting now reuses atlas execution's existing launcher-dependent host-directory
policy. Native execution retains its `cwd`. WSL and container execution use their
explicit directory options and omit the redundant host `cwd`. Command previews,
source runtime/device/thread settings, PCA values, endpoint momenta, topology
checks and atomic publication remain unchanged. A user can retry the existing
verified design; no atlas or PCA rerun is required, and nothing starts
automatically.

Validation includes native/WSL/container endpoint-publication regressions in
deep directories, source and result tampering checks, and the Windows launch
boundary reproduced with a non-scientific child process. Native WSL directory
selection succeeds for the same long directory. Owner endpoint anatomy and
atlas quality remain separate from this launch correction.

Build and installation evidence will be recorded separately after verification.
