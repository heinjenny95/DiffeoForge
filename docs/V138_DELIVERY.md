# v138 — verified Windows build; installation pending

Runtime/build commit: `57b62783c004414c69dfeb029a4e35c87baa6074`.
Version: `0.0.0.dev138`. Later completion changes affect tests, CI and documentation
only; runtime source and build inputs remain byte-identical to this commit.

The owner-authorized [desktop backlog](V138_DESKTOP_BACKLOG.md) and
[follow-up repairs](V138_FOLLOWUP_AUDIT.md) are included in the tested build.
The current installed application remains v137 because the owner's atlas and
execution worker are active. No installation or new scientific run was performed.

## Build and artifact verification

The clean Windows freeze contains five entry points: desktop, general worker,
reference worker, reference execution worker and reference preparation worker.
All **3,457 bundle files** (1,391,385,598 bytes), dependency metadata, SBOM and
evidence companions pass verification. Startup/worker protocol and preparation
engineering smokes pass. The pinned compiler produced one local private-alpha
installer; its complete evidence and checksum verification pass.

| Artifact | Verified value |
| --- | --- |
| Installer | `DiffeoForge-v138-Windows-CPU-x86_64-Setup.exe` |
| Installer bytes | 458,552,598 |
| Installer SHA-256 | `f0243bbbf14e0a5b4d295064be46010749819c6995471abe7e8622eb73595d7d` |
| GUI EXE SHA-256 | `db943d87dd8a49c01521418e4bca99306fce1d5833e2b61a57fcca7606a6f38b` |
| GUI PYZ SHA-256 | `a11527cdd356ef748061f4b48708a9435d070885f8b530928990cacd08379191` |
| Bundle inventory SHA-256 | `c6286de1eb03500acb3c988df0c36a9320682c5f107477d61aa1db03e11531e3` |

An independent probe entry point uses the exact product PYZ and runtime files.
It verifies saved-method labels, unchanged 3D coordinates, current-camera export,
PNG/JPEG decoding, duplicate-export rejection, asynchronous exports, both theme
modes, owned-dialog styling, full-width cap advice and the export-only request.
All ten source/frozen PNG comparisons are byte-identical. Demo modules and assets
are absent from the new bundle. Normal frozen GUI/probe shutdown succeeds.

## Regression scope

The final Windows desktop and v138 regression run passes **375 tests**, with one
expected environment skip, and exits normally with code 0. It covers the existing
setup/review/viewer/worker route and the new method, cache, theme, media, study and
fault cases. The 30-case follow-up suite is included in that scope. Earlier
focused worker/protocol/advice and 94-case source runs provide additional,
overlapping checks; their counts are not additive.

A mixed broader Windows run previously aborted with an access violation. The
nearby isolated legacy qualification case passes in 110.36 s. Test fixtures now
dispose closed test windows while QApplication is alive and isolate appearance
preferences; the final desktop run above has a clean process exit. A complete
mixed-suite pass is not claimed. The headless helper import, Linux CI multimedia
prerequisite and specific harmless Qt startup INFO expectation are also repaired.
Cloud CI reruns are tracked separately from the local build checks.

The WSL process-only cancellation probe passes, with unchanged synthetic state
and an unrelated live process. This does not qualify cancellation during a native
scientific GPU run or establish scientific/anatomical acceptance.

## Installation and distribution

Safe installation still requires a fresh idle-application/backend check and a
verified recoverable backup. Existing installation authorization is retained;
an active atlas is not interrupted to install. Installed UI and registry checks
remain pending that step. The older incomplete build attempts are superseded.

The installer is unsigned and remains a local engineering/private-alpha build.
No Drive upload, public release, tag, merge, signing claim or external platform
qualification is implied. Source, frozen build, installed and distributed states
remain separate. Scientific settings, original results and human QC are preserved.
