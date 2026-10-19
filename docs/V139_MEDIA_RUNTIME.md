# v139 — frozen media runtime repair

The frozen desktop could generate the native mean and PC endpoint meshes, then
fail when preparing their views because imageio looked up distribution metadata
that was absent from the bundle. Startup and direct FFmpeg recording checks did
not exercise this imageio import and plugin route.

The Windows spec explicitly collects imageio and imageio-ffmpeg metadata. A new
frozen media build gate encodes and decodes four synthetic MP4 frames through the
same imageio/FFmpeg route as the PCA movies, checking frame count, dimensions and
content. It opens no scientific project and launches no native scientific job.

Visualization preparation checks this runtime before native Shooting and honors
a cancellation during that check. Existing verified endpoint results are reused
on retry. Failure text identifies visualization preparation and keeps the atlas
and PCA available, rather than implying that all PC shapes failed.

Source checks cover successful encoding/decoding and cleanup, missing metadata,
early failure/cancellation, the freeze contract and existing media/view handling.
Automatic result preparation after convergence remains a separate backlog item.

## Verified Windows delivery

Runtime/build source: `32f858774381bdfe96613bb670735dc0557a8b54`.
Version: `0.0.0.dev139`. Later delivery documentation does not change runtime or
build inputs.

- All 27 focused regression cases pass with clean process exit, including the
  frozen contract, early failure/cancellation and reuse of existing endpoints.
  Ruff, whitespace checks and the source media smoke pass.
- The five-entry Windows freeze and local installer evidence pass, including
  startup, worker/protocol/preparation checks and the new frozen media gate.
  An independent invocation of the exact frozen desktop media smoke returns 0.
- After a complete verified backup, saved normal closure and fresh idle guards,
  the installer returns 0. All 3,472 installed bundle files and six evidence
  companions match the tested build; registry version and both imageio metadata
  directories are correct. Installed media encode/decode and startup smokes
  return 0. Existing project contents remain byte-identical after installation.
- The installed GUI is reopened through the ordinary Windows shell and its
  independent process identity is checked again after the launcher exits.

| Installer | Verified value |
| --- | --- |
| Filename | `DiffeoForge-v139-Windows-CPU-x86_64-Setup.exe` |
| Bytes | 458,577,962 |
| SHA-256 | `b701b9c3e6d824b8eaaf9c4cfe53613505d87cdeabce12b2f8dba1f580139eb6` |
| Bundle inventory SHA-256 | `0f0f141bdcfd7abf1688860c537d833cd2e7ca746a565b20610e84c7c3d7bfcc` |

This is an unsigned local private-alpha build. No Drive upload, public release,
cross-platform qualification, full mixed-suite pass or new scientific validation
is claimed. The atlas and PCA are not rerun to repair visualization preparation.
