# Private-alpha build numbering

## v85 — a selected run folder always gets a visible answer

Development candidate v85 (`0.0.0.dev85`) addresses #193. A researcher selected
the correct folder of a crashed Deformetrica run several times and saw no
reaction. Read-only inspection found the run already recorded as `interrupted`
without any checkpoint, so none of the three entry points could use it. The
outcome of **Resume interrupted run…** and **Recover after crash…** was written
only to a status label on the parameter page, not to the first screen that holds
the buttons, and named only what was *not* found.

- Both verifying lookups now run in a background worker. The selected path and a
  read-only notice appear on the first screen, the clicked button reads
  *Inspecting selected folder…*, and all three entry points are locked so repeated
  clicks cannot queue duplicates.
- Every outcome without a usable run is shown in a dialog and kept in the
  first-screen status line until the form is edited. It states what the action
  looks for, which folder level to select, what the location contains instead
  (completed / stopped with checkpoint / stopped **without checkpoint, cannot be
  continued** / still `started` / prepared / unrecognized), which action fits
  that state, and the verifier's reason when a matching run was rejected.
- A selection inside a run folder, at the `runs` folder, or one level above a
  project is answered with the folder to select instead.
- Classification reads only `manifest.json`, `result.json` and the tail of
  `events.jsonl`; it never hashes, traverses recursively, or writes. Discovery
  keeps its fail-closed verification and additionally returns rejection reasons.
- Two mis-encoded separators in the crash-recovery dialog were corrected.

No metric definition, engine, protocol or schema version changed. A run that
stops before its first completed checkpoint remains unrecoverable; v85 only says
so. Nothing has been frozen, built, installed or published at this point.

**Delivery observation (2026-09-18).** v85 was built from the pull-request head
`ffdd4e1` with a clean worktree after all ten CI jobs passed, and installed
locally; nothing was published. The squash merge `e6cc19e` (#194) has an
identical tree (`git diff ffdd4e1 e6cc19e` is empty).

- The editable-package metadata was refreshed to `0.0.0.dev85` before freezing;
  the dependency freeze before and after was identical, and every
  package/version guard passed on the first attempt.
- Frozen bundle: **2,677 files**, 764,867,860 bytes, inventory SHA-256
  `69ff9c89d3e07e1b2218ed6de2080ef3db8fbf45deeb417efa2b99a4ff0ee5d8`; SBOM with
  27 components. The portable Inno toolchain evidence observed on 2026-09-05 was
  reused unchanged.
- `DiffeoForge-v85-Windows-CPU-x86_64-Setup.exe`: 323,034,528 bytes, SHA-256
  `60934733637329ea79acbcbb3d1aaeb081cdbe22f3f19d5b5469c3c0239f4085`,
  Authenticode `NotSigned` as intended for the private alpha.
- DiffeoForge was closed and no WSL distribution was running. The v84
  installation (**2,688 files**) was copied to a separate backup and every file
  hash-compared without a mismatch.
- The silent per-user setup exited 0 without a restart. All 2,677 inventoried
  files plus the freeze-evidence pair are byte-identical to the built bundle; the
  only other installed files are the licence, the uninstaller pair and six
  evidence files. Installed `DiffeoForge.exe` SHA-256:
  `01a5c4e3656ee4f5b3ac745c2b934e3289c65be8f28d65c2f63c20a5cc1d40a3`. The window
  title read **DiffeoForge v85 (Private Alpha)**.
- A read-only dry run of the new explanation against the affected run folder
  named the missing checkpoint, and against the folder one level above the run
  root named the folder to select instead; the run folder was not modified.
- Not observed: the new dialogs and button states were exercised by tests only,
  not inspected on screen in the installed build, and researcher
  landmark/configuration/review metadata were not separately backed up.

## v84 — recent projects on the first screen and unattended outward search

Development candidate v84 (`0.0.0.dev84`) packages two merged changes: the first
screen now offers up to eight recently opened projects and prefills the last one
(#190), and an unattended AFK pilot may widen a boundary-limited search up to
four times the tested maximum, writing `automatic_search_budget_exhausted` when
that budget ends (#191). No metric definition, engine, protocol or schema
version changed.

Both pull requests passed all ten CI jobs on their own heads and were
squash-merged into `codex/deformetrica-first-workflow` as `c607efd` and
`e31ac9b`. This version bump is the first run that exercises the combined state.
Nothing has been frozen, built, installed or published at this point; the
freeze, dependency-metadata/SBOM, installer-build and installation evidence for
v84 are still outstanding, and no researcher project or scientific input was
changed.

**Delivery observation (2026-09-17).** v84 was built from `b6a26dd` with a clean
worktree and installed locally; nothing was published.

- The first packaging attempt correctly stopped at the installer plan on stale
  v83 editable-package metadata in the local build environment, as in v79. The
  metadata was refreshed with `pip install --no-deps -e .`; the dependency
  freeze before and after was identical. A fresh freeze then passed every guard.
  The rejected attempt was never installed or distributed.
- Frozen bundle: **2,677 files**, 764,809,085 bytes, inventory SHA-256
  `044f1474a95fcd9f2df33186b561ad8bfcfefaa7a97ea153a85c3718a9dc0686`; SBOM with
  27 components. The portable Inno toolchain evidence observed on 2026-09-05 was
  reused unchanged.
- `DiffeoForge-v84-Windows-CPU-x86_64-Setup.exe`: 322,987,739 bytes, SHA-256
  `c90850f2e33457b243f5b5149a6c0a585d2f5d7b49b23d9c9dcc6239a46f1f22`,
  Authenticode `NotSigned` as intended for the private alpha.
- The closed v83 installation (**2,687 files**) was copied to a separate backup
  and every file hash-compared without a mismatch.
- The silent per-user setup exited 0 without a restart. All 2,677 inventoried
  files plus the freeze-evidence pair are byte-identical to the built bundle; the
  only other installed files are the licence, the uninstaller pair and six
  evidence files, with no v83 remnants. Installed `DiffeoForge.exe` SHA-256:
  `b80f163ce8e95790699687d499153dcb6eecfcfbb6b1a95e04556176eb788c08`. The window
  title read **DiffeoForge v84 (Private Alpha)**.
- Not observed: the preselected Reference engine, the **Recent projects…** entry
  and the AFK outward-search checkbox were not inspected on screen, and
  researcher landmark/configuration/review metadata were not separately backed
  up. The installer writes only to the per-user installation directory.
- `tools/desktop_installer_plan.py --output-directory` and
  `tools/observe_installer_build.ps1 -EvidenceOutputDirectory` require an
  existing empty directory, unlike the other steps, which require a new path.

## v83 — workflow clarity, activity feedback and QC mesh retention

Development candidate v83 (`0.0.0.dev83`) defaults new GUI projects to Reference,
collapses routine project/comparison detail, shows real window-scoped activity,
and streams QC mesh objects without changing metric definitions. AFK uncertainty
and optional fixed-noise Validation Lab scope are explicit. See the
[implementation and limitations](V83_WORKFLOW_USABILITY.md).

Initial runtime candidate `16a3a1b` passed CI, public container comparison and
160 regressions against its frozen changed modules (one expected dependency
skip). Its private installer was built and verified, not installed or published.
Follow-up candidate work addresses narrow-window control clipping; candidate
source commits and package hashes must be distinguished even before first local
installation. No researcher project or scientific input was changed.

### Verified local v83 delivery

On 2026-09-16, the user authorized installation of the tested private candidate
from clean runtime snapshot `e6e322b215512e19c28198354f5a9e9dc2967aa4`.
Subsequent `9cecc6e` changes concern tests/CI/docs only; application, installer
and dependency files are identical to that runtime build. All three final CI
workflows passed, including the isolated Windows installer lifecycle.

The existing v82 app was closed normally after desktop access was restored.
Its complete 2,687-file installation was preserved in a separate, hash-verified
backup. The v83 setup completed without a Windows restart. All 2,676 bundled
application files match the built inventory; source/version evidence, the desktop
shortcut and Windows registration were verified. The installed startup smoke
passed and the native app reopened as **DiffeoForge v83 (Private Alpha)**, with
Deformetrica Reference selected on the empty new-project page.

Protected research files remained byte-identical; saved landmark/configuration/
review metadata were separately backed up. No atlas or Validation Lab run was
started. This is authorized same-owner local delivery, not a signed public
release, independent first-use acceptance or scientific validation.

- Installed executable SHA-256:
  `90392c5a2daad734976190d4d6054321be44860c2955b95d6ec6bb108258fb66`.
- Installed setup SHA-256:
  `5615ade86a4ceb508f0e767676720dc3475f7aa4995e690b2432ce21df88594f`.

## v81 — pilot preparation after switching engines

Private Windows build **v81**, package `0.0.0.dev81`, fixes a silent no-op in
the guided Deformetrica pilot. After creating a Modern project and switching
engines, stale Modern project/review objects could skip Reference preparation;
the UI said "Checking" although no readiness worker had started.

Engine changes now clear only engine-bound in-memory project/review/run evidence.
Input paths, landmarks, approved GPA alignment and current geometry-analysis/pilot
plan inputs are retained; existing configurations and results are never deleted.
The pilot entry point independently rejects stale cross-engine evidence and
prepares the correct configuration. Normal same-engine continuation is preserved.
The engine selector is locked during a foreground worker, repeated pilot clicks
cannot queue duplicates, and the pilot card describes the actual preparation
worker. A readiness check without a Reference review gives an actionable warning.

Eleven focused regressions cover both switch directions, stale result/review
combinations, twenty repeated invocations, same-engine continuation, preservation
of files/alignment, worker locking and invalid-readiness feedback. The combined
desktop/pilot/readiness suite passed **76 tests**; one dependency-absence test was
correctly skipped because PySide6 is installed. Local delivery is verified
separately. No scientific parameters, solver mathematics, display geometry or
landmark coordinates were changed; this is not a scientific validation claim.

The broader source suite passed **271 tests** (the same one dependency-absence
skip), including GPA/frame synchronization, landmark picking/rotation/drafts,
display proxies, preprocessing, QC release gates and packaging contracts.
Ruff and whitespace checks passed.

### Verified local v81 delivery

Runtime snapshot
[`375249a`](https://github.com/heinjenny95/DiffeoForge/commit/375249ae41e33591ed8aebfdb7a4fd4d0eda51e9)
was clean-built, packaged, installed and reopened with the user's approval on
2026-09-15. The same **271 regressions passed** against the embedded window and
shared rendering modules (one dependency-absence skip). Both changed Python
modules matched the committed source exactly; all **62 versioned JSON schemas**
and **2,676 installed bundle files** were verified. Startup, worker and
preparation smoke checks passed. The previous **2,687-file installation** was
retained in a separate, hash-verified backup.

All **170 existing study/input/project files** remained byte-identical through
installation; landmark, configuration and GPA evidence files were additionally
backed up. Original input paths and alignment settings were restored in the
native app. In-memory visual GPA approval must be reconfirmed by the user after
restart; no approval was fabricated and no scientific pilot or atlas was started.
This remains an unsigned, same-owner Windows private alpha, not a public release.
Private inputs and local installer artifacts are excluded from GitHub.

- Installed executable SHA-256:
  `86b54db2478e4a934830796c4057ca2f1af7553d78f1a0e40b003bca22663b20`.
- Local setup SHA-256:
  `86afa8c69bfabaff21c763c4ffdf14b83bf6a0d83b3d3e0c1c2d9341f2211b2f`.

## v80 — synchronized GPA review overlays

Private Windows build **v80**, package `0.0.0.dev80`, binds the selected,
cohort and consensus GPA landmarks (including labels) to the camera and viewport
of the displayed mesh image. Pending rotation, pan, zoom, resize, preset and
reset requests no longer move markers ahead of the asynchronous surface frame.
Cohort/selection, resolution and geometry-layer changes invalidate stale images;
markers stay hidden until a matching frame exists. Failed/cancelled frames never
advance the overlay, and pending/error views are labelled.

This is display-only: source meshes, landmark coordinates, GPA transforms,
residuals and review approvals are unchanged. Large cohorts can still render
slowly, with surfaces and markers now waiting together; no frame-rate guarantee
or scientific validation is claimed. The existing v79 landmark-editor rotation
behaviour is retained; this update does not redesign GPA rotation controls.

Two new painted-pixel delay checks reproduce the bug against the committed v79
GPA canvas (rotation and resize). The focused GPA suite passes **38 tests** with
the fix. Coverage includes all overlay roles, reduced/original display modes,
visibility/selection changes, failed/superseded frames and array immutability.
The private-alpha packaging tests now derive the expected filename from the
current package version, replacing stale v78 fixture literals without weakening
the exact-file or tamper checks. Installed delivery is verified separately.

The final targeted source suite passed **195 tests**, including existing GPA,
preprocessing, landmark/picking/draft, background-render, QC release and packaging
safeguards. Ruff and whitespace checks passed. Package metadata was refreshed to
v80 before freezing; runtime dependencies were not upgraded.

### Verified local v80 delivery

On 2026-09-15, runtime snapshot
[`cfe369b`](https://github.com/heinjenny95/DiffeoForge/commit/cfe369b23675c4612bf7cc4ffabc35f6b25cbb6e)
was clean-built, packaged, installed and reopened with the user's approval.
All **2,676 installed bundle files** were hash-verified, all **62 versioned JSON
schemas** matched source, and startup/worker/preparation smoke checks passed.
The previous installation was retained in a separate, hash-verified backup.

The final **195 regressions passed without skips** using the embedded GPA and
rendering modules. A test-only tight polling loop had starved a render worker;
switching the wait helper to a native Qt event loop fixed that timeout while
retaining the same ten-second deadline. This later test/documentation change
does not change the installed runtime snapshot.

Saved landmarks and mesh inputs remained byte-identical. Restoring the original
inputs/settings reproduced the exact pre-update read-only GPA fingerprint.
The reopened native GPA viewer passed a rotate/reset smoke check: overlays stayed
with the old frame while pending, then followed the newly rendered surface.
Visual approval must be reconfirmed by the user; no project, atlas or validation
run was started. This remains an unsigned, same-owner Windows private alpha,
not a public release or scientific validation. Private study data and local
installer artifacts are excluded from GitHub.

- Installed executable SHA-256:
  `e5040b32bb786430f6409aa5e906cd36aab76038aa4004e2de3564ff41d2e8ef`.
- Local setup SHA-256:
  `2a70de9fea192f830ccddc648703f4572b480b9cbea6effdc4da40c62d426446`.

## v79 — screen-relative landmark rotation

Private Windows build **v79**, package `0.0.0.dev79`, changes the landmark
canvas from accumulated fixed-axis yaw/pitch to composed camera-axis rotations.
The visible near surface follows left/right/up/down mouse drags even after
turning the specimen upside down or viewing it from a pole. Diagonal drags use
one reversible axis-angle increment. Drag sensitivity, pan, zoom, view presets,
stored mesh coordinates and saved landmark coordinates are unchanged.

Rendering, surface picking and frame-cache identity use the same complete
orientation matrix. The v78 displayed-frame marker synchronization remains in
place. This also affects neutral viewers using `InteractiveMeshCanvas3D`; other
independent comparison/GPA canvases are not changed by this targeted repair.

The screen-displacement regression reproduces v78's inverted horizontal movement
in an upside-down view (two expected failures with the previous canvas), then
passes with the repair. The initial focused suite passed **74 tests**, covering
all seven view presets, upside-down/mixed drags, 10,000 orthogonal rotations,
inverse diagonals, pan, picking, delayed rendered markers, drafts and build labels.
Existing user landmarks are backed up and restored, not discarded for this update.

The expanded final source suite passed **197 tests, with one unavailable-Windows-
symlink-privilege skip**, including an independent analytic ray/cube check after
composed rotations, viewer/QC release safeguards and packaging/evidence contracts.
Ruff and whitespace checks passed. This is display/input verification, not a
scientific validation or a claim that every independent viewer was redesigned.

### Verified local v79 delivery

On 2026-09-15, runtime snapshot
[`70b9fbd`](https://github.com/heinjenny95/DiffeoForge/commit/70b9fbd7a2e347a91da11a87da5327196f1f82a5)
was clean-built, packaged, installed and reopened with the user's approval.
Later documentation-only commits record delivery, not a different runtime.

- **91 tests passed against the final embedded landmark/render modules**. Both
  changed runtime modules matched compiled committed source; all **62 versioned
  JSON schemas** matched byte-for-byte. These overlap the source tests above.
- Installed startup smoke passed; all **2,676 bundled files** were hash-verified.
  App and editor titles show `v79 (Private Alpha)`; the Desktop shortcut targets
  the verified executable. A native drag rotated the displayed mesh without
  adding, replacing or dropping landmarks; the view was reset afterwards.
- The previous application was preserved and all **2,687 previous files** checked.
  The existing landmark draft was separately backed up, natively validated and
  resumed at the previous specimen. Its bytes and saved coordinates remained
  unchanged after reopening. Reduced-view picking and auto-advance are active;
  no anatomical points, QC approvals or study computations were created.
- The first packaging attempt correctly stopped on stale v78 editable-package
  metadata in the local build environment. After refreshing that local metadata
  to v79 without dependency upgrades, a fresh build passed all package/version
  guards. The rejected attempt was never installed or distributed. Future
  numbered builds must check editable metadata against `pyproject.toml` first.

Retained local v79 artifact identities (SHA-256):

```text
DiffeoForge.exe
d85fe022818a94462098d48c5db790a7c605331cd411db0469c2c94387c2d0a5
DiffeoForge-v79-Windows-CPU-x86_64-Setup.exe
50288443d09bf9ae9a87ad646ca17139bc69da6fe0b3c83d27e4d7b6513e0ea9
```

This remains an unsigned, same-owner Windows private-alpha installation, not a
public release or scientific validation. Private data and installer artifacts
remain outside GitHub. User landmarking and anatomical review are the next step.

## v78 — synchronized landmark overlays and visible build identity

The previous private Windows test build is **v78**, package version
`0.0.0.dev78`. The main window and landmark editor show `v78 (Private Alpha)`;
the installer name is `DiffeoForge-v78-Windows-CPU-x86_64-Setup.exe` and its
installation entry shows the same label. CLI/Qt metadata retain the PEP 440
package version. The frozen evidence records the exact source commit.

Landmark overlays now use the camera of the displayed mesh image, including
while a newer image is pending. Meshes, saved coordinates, scientific algorithms
and QC approval requirements are unchanged. See `LARGE_MESH_VIEWER.md`.

Source verification: 155 focused tests passed, with two environment-specific
skips (installed PySide6 and unavailable Windows symlink privilege). Coverage
includes painted-frame synchronization, proxy picking, original-surface transfer,
editor drafts, main-window behavior and installer/freeze/SBOM contracts. Ruff and
whitespace checks passed. Installed-binary verification is recorded separately;
these tests are not a completed anatomical or end-to-end scientific validation.

A further 66 viewer/QC/CLI tests passed. The first installer-plan attempt correctly
stopped because its legacy schema allowed nine arguments, while the numbered
alpha adds a tenth display-label define. The schema now permits that extra
argument; exact plan reconstruction still rejects arbitrary argument changes.
The compiler-observation wrapper and retained build-evidence verifier/schema
also accept exactly ten arguments for numbered alphas, keeping nine for legacy
and release versions. Both version families run through the full evidence tests.
A full create/validate/reconstruct regression covers v78, and the clean binary
was rebuilt with the corrected schemas before installation. The stopped attempt
was not installed or distributed.

### Verified local delivery

On 2026-09-15, the final runtime source snapshot
[`9250632`](https://github.com/heinjenny95/DiffeoForge/commit/9250632bdaceb418e92cea93aeba743d0c080238)
was clean-built, packaged and installed for the existing local user. Later
documentation-only commits record delivery; they are not the runtime snapshot.

- Consolidated source regressions: **222 passed, 2 environment skips**. The final
  numbered-alpha packaging/evidence checks passed (**33 tests**), as did
  distribution/Windows/reference-installer contracts (**15 tests**). These
  overlapping suites are not an additive unique-test count.
- **48 landmark/render tests passed against the embedded executable modules**.
  All six changed runtime modules matched the committed source after compilation,
  and all **62 versioned JSON schemas** matched byte-for-byte. Build-only modules
  were correctly absent from the application bundle.
- Installed startup smoke passed; all **2,676 bundled files** were hash-verified.
  App/editor titles visibly show `v78 (Private Alpha)`, and the Desktop shortcut
  points to the verified installed executable.
- The previous application was backed up and all **2,687 previous files** checked.
  The existing on-disk landmark draft was separately preserved; unsaved trial
  placements were discarded with the user's permission. The editor reopened with
  **0/159 points**, LM1-LM3, auto-advance enabled, a reduced display and no paused
  autosave warning. No fictitious anatomical points were placed for verification.
- All 106 original/prepared mesh hashes remained unchanged. No study atlas or
  Validation Lab computation was started; anatomy and QC still require review.

Retained local artifact identities (SHA-256):

```text
DiffeoForge.exe
63fa9a43b73f3222dcc1367f8a1cc42e461e076b069bcc19093d399958cd5f6e
DiffeoForge-v78-Windows-CPU-x86_64-Setup.exe
72bd5beeba7c8425904f56641b86c6b0052d7bf9dfdc0235cc3d523877d9cd63
```

This is an unsigned, same-owner private-alpha test installation, not a public
release or completed scientific validation. Installer artifacts and private
research data remain outside GitHub.

## Reconstructed numbering gap

On 2026-09-15, the local installation backups were inspected to recover the
sequence after the explicitly labelled v71. **v72–v77 below are retrospective
sequence labels**, not claims that those historical binaries displayed them.
All those installers still used the stale package placeholder `0.0.0.dev0`.
No archived manifest or executable was rewritten.

| Label | Runtime source | Installed change |
| --- | --- | --- |
| v71 (original label) | `705a110` | Shape-space roundoff compatibility |
| v72 (reconstructed) | `c4d37f6` | Native landmark-import update |
| v73 (reconstructed) | `53b2bae` | NAS project-staging update |
| v74 (reconstructed) | `e9a4a0e` | Post-atlas QC update |
| v75 (reconstructed) | `8670974` | UX, AFK pilot, proxies and validation progress |
| v76 (reconstructed) | `063143a` | Background-renderer lifetime repair |
| v77 (reconstructed) | `3f31712` | Reduced-view landmark placement |
| v78 | See frozen build evidence | Frame-synchronous markers and explicit numbering |

The sequence is bound by the source fields in the installation backups made
before the JSON, NAS, QC, UX, renderer and landmark-proxy updates, followed by
the installed landmark-proxy build. Private backup locations are not published.
This numbering does not imply scientific validation, a public release, or an
engine/protocol version change.

## Required for every subsequent packaged change

1. Advance the private build number without reusing a shipped number.
2. Update `pyproject.toml`, `diffeoforge.__version__`, the handoff contract and
   its packaging wrapper together. `tests/test_build_version.py` rejects drift.
3. Add the change and test scope here; retain source commit/hash in build evidence.
4. Verify the window title, installer label/name and installed bundle identity.
5. Update GitHub and the Google Docs Project log. Do not publish installer
   artifacts or private research data without separate authorization.

Updating the version is not automatic for every Git commit: documentation-only
commits and intermediate source work are not additional installed builds.
