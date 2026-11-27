# Next-version private Windows test build — 2026-09-14

The current usability package is implemented, packaged and installed for same-owner
local testing after separate user authorization. This is not a signed release or
scientific qualification.
The larger roadmap is planned in [NEXT_VERSION_PLAN.md](NEXT_VERSION_PLAN.md), not
claimed complete.

## Included changes

- Background Validation Lab opening, study preparation and preflight, with safe
  cancellation and explicit launch confirmation.
- Whole frozen training-plus-holdout progress, distinguishing backend completion
  from verified evidence; original-start wall time where the ledger records it.
  Legacy unknown starts stay unknown. Pauses count as wall time, not compute time.
- Bounded cached display proxies across mesh viewers, including settled frames;
  original scientific geometry is unchanged. Exact picking and visual QC require
  original-detail inspection. See [LARGE_MESH_VIEWER.md](LARGE_MESH_VIEWER.md).
- Explicitly authorized bounded [AFK pilot](AFK_PILOT.md), with provisional
  decisions, preserved visual rejections, safe stops/resume and a return summary.
  No outward extension, invented visual approval or automatic atlas launch.
- Shorter default guidance, collapsed explanations and visible mandatory warnings.

## Exact local build identity

Runtime source: `8670974e3af1232d5e9c4f0cb3959068f8e9be62`.
All 19 changed Python modules embedded in the EXE were compared with compiled
source from that commit and matched exactly; the configuration schema also matched.
Subsequent test/documentation corrections do not change this runtime.

| Evidence | Recorded identity |
| --- | --- |
| Program bundle | 2,676 files; 764,613,165 bytes |
| Freeze evidence SHA-256 | `8b76e747c8a5c6dfab6b5871e916f05a32f78b3ec12cd00ce73b35a0752783d8` |
| Setup | 322,786,786 bytes; subsequently installed locally with separate authorization |
| Setup SHA-256 | `5a00e4bef45178c2398d884525c53445f11156b10d5461420c49daff22f8d88f` |
| Private handoff manifest SHA-256 | `e8386a417e4a7fcda90a5576d38000df5b6bc0fd2acb1f6ed092f72f30a187ea` |

The existing freeze contract passed GUI startup, public synthetic Modern execution,
reference/preparation-worker smokes, cancel-before-prepare and hard-parent-death
checks. The complete bundle, dependency inventory, unreviewed/incomplete CycloneDX
SBOM and exact six-file private handoff were independently verified. These checks
do not execute an overnight clinical pilot or establish numerical/biological validity.

## Regression-test observations

The expanded source suite passed 171 tests with one inapplicable skip; the separate
viewer/Validation Lab suite passed 88 tests. An isolated GUI suite passed 103 tests
with one skip. Ruff and whitespace checks passed. A test expectation retaining the
old misencoded crash-recovery button label was corrected without changing runtime.

Repeated combined runs produced a native Qt access violation without an actionable
Python application frame. A passing identical run did not resolve it. Narrowing
reproduced the fault in the old standalone comparison-canvas test, without AFK:
that test returned while its first asynchronous frame was still pending. It now
waits for the actual current frame to be presented before capture and teardown;
20 fresh-process replays passed. The new AFK GUI test additionally retains a
session-lifetime QApplication, explicitly disposes its dialogs, and uses a plain
dispatch spy rather than abandoning a real, unstarted QRunnable. Those changes
alone had not resolved the old canvas test's race.

Independent native-event-loop stress checks completed 60 pilot open/close/GC cycles
and 60 viewer cycles, including early closure. This is test-lifecycle evidence,
not a runtime code change or a universal Qt stability guarantee. The failed
observations are retained privately alongside the passing logs.
The final combined rerun after this test hardening passed all 171 applicable tests
with one expected skip in 128.53 s. No application-source change was needed after
the verified installer was built.

## Large-mesh UI observation

One private 477,334-face mandible was shown with 4,541 display faces. In a native Qt
event loop, loading plus the first display took 3.71 s, with 254 GUI timer callbacks
(10 ms median interval; 0.66 s maximum gap). This observation ran alongside build
and test work. The source hash was unchanged and exact picking remained disabled
on the reduced view. A separate single-frame observation measured 45 ms proxy
rendering versus 3.55 s for the full original. This is not a universal latency or
anatomical-detail guarantee; fine tooth details can be hidden by simplification.

## Authorized local installation

On 2026-09-14, the user explicitly approved installation of this test build. No
DiffeoForge process was running at preflight. The previous application (runtime
`e9a4a0e07fe4fb65350350096bf7a746fb296230`) was preserved in a separate backup;
all 2,687 previous installation files were hash-verified after the move.

The six-file private handoff was verified against its external manifest hash
before setup. Current-user installation completed with exit code 0, without
closing applications or requiring a Windows restart. All 2,676 installed bundle
files and the freeze evidence matched the build identities above. The installed
EXE SHA-256 is
`a977e9143700a236d37a791c6406ef02001d754489083bdf2d591746ab281ab8`.
The desktop shortcut targets that executable, and the installed offscreen GUI
startup smoke exited successfully (code 0).

This operation did not modify scientific projects, source data or study ledgers,
or start an atlas, pilot or Validation Lab job. Installation logs and backup
inventories remain private. The build/packaging manifests retain their historical
non-execution observations; the later authorized installation has separate evidence.
A short separate-project AFK/viewer/Validation Lab acceptance test is still pending.

## Boundaries and next steps

- Installer Authenticode: `NotSigned`. Microsoft Defender was disabled, so no
  targeted Defender scan was performed. Security-product inventory is not malware
  clearance. No signing, clean-VM, public release or redistribution approval is claimed.
- The authorized installation replaced only the application and its installation
  metadata/shortcuts, with the previous application retained for recovery. Existing
  scientific studies, datasets and QC decisions were not changed.
- New AFK configuration provenance requires this version or a compatible newer
  schema reader. Old software may reject the new selection-mode value.
- GPU/HPC, platform qualification, multiresolution/independent anatomical studies,
  external usability, release signing and archival/manuscript work remain gated
  follow-ups. Internal tests do not complete those larger roadmap items.

Private meshes, rendered anatomical figures, installers and local build paths
are deliberately excluded from the repository.
