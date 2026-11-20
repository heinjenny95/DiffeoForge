# v129 — verified local Windows delivery

Verified on 18 October 2026. Runtime source commit:
[`7ca287a426a29c12a0295cd2c7228dadc1f0db9e`](https://github.com/heinjenny95/DiffeoForge/commit/7ca287a426a29c12a0295cd2c7228dadc1f0db9e).
The installed application and registry both identify **0.0.0.dev129**. Later
delivery-documentation commits do not change the embedded runtime source.

## Build and installation

The clean-source Python 3.12/PyInstaller 6.21 Windows CPU build passed ordinary
GUI, Modern synthetic-worker, Reference preparation, queued cancellation,
uncancelled startup and parent-death engineering checks. The frozen payload
contains 3,461 inventoried files (1,390,809,126 bytes), plus its two freeze-evidence
files. Dependency metadata and a CycloneDX 1.7 SBOM record 27 packages; the SBOM's
composition remains explicitly incomplete rather than a redistribution approval.

The versioned local installer compiled and independently verified successfully:

- Setup SHA-256: `e688f2ad66c0fab90a27f7b98e90f49109a6ef6961549bcadf0088cd0d1cedff`.
- Installed GUI SHA-256: `9440374a8484a87703d6d906b0afbddf656d8adc4a34eb9290c331724d668e30`.

A complete 2,846-file v128 backup was copied and hash-verified. Fresh Windows/WSL
idle guards passed; both the backup and old installation were rechecked before
replacement. Setup returned zero without a Windows restart. All 3,463 installed
bundle files, six companion evidence files and application license match the
verified build. Only the expected license, uninstaller and evidence companions
are additional files. Protected completed-result receipts remain unchanged.

The actual installed GUI passed its ordinary startup smoke. It was reopened
through Windows Explorer, with executable, creation time and service-brokered
shell ancestry verified outside the assistant's process tree. No scientific
computation was dispatched.

## Feature acceptance

Source regressions covered guided pilot reopening/layout, completed/density
workflows, full-detail/proxy cache invalidation, result release, deferred dispatch,
closed-window and cancellation guards, native grid receipts and iteration-budget
provenance. Public native fixtures checked all seven full mean/PC1–PC3 endpoints
and all 51 display samples, anchor agreement, physical t=1 on the declared grid,
source preservation and complete gallery/video output. The full background
QThreadPool preparation/render/export pipeline passed.

A separate frozen engineering entrypoint reused the desktop's byte-identical
PYZ, runtime hooks and bundled dependencies. It then repeated against the actual
installed runtime. Both checks passed:

- Seven workflow pages, three SD/movie axes and twelve heatmap views.
- Six VTK views, Matplotlib output and the bundled FFmpeg encoder/license files.
- Native in-app PC3 playback: 4.75 seconds, 58 frozen / 59 installed decoded
  frames, no decoder error and visible CPU video frames.
- Verified archive export with matching inventory hash and same-result cache reuse.
- A selected pilot using 198/200 iterations recommends a new budget of 500.

These media checks use public synthetic fixtures and existing prepared media,
not a private atlas/PCA rerun. Pilot layouts were visually checked at 850×650 and
1040×820; installed SD/video screenshots were inspected separately from unit tests.
See [behavior and limits](V129_PILOT_AND_VISUALIZATION.md).

## Boundaries

This is a private local development installation. No installer upload, public
release, tag or merge was performed. The previously distributed installer is
unchanged. Public-release, independent first-use and scientific validation gates
remain separate. The full native media qualification used Float32 KeOps; the
isolated Float64 adapter fixture used Torch-Gaussian and does not qualify an
arbitrary Float64 KeOps runtime. Original results, approvals and ongoing server
work are preserved. A budget recommendation is not a convergence guarantee;
checkpoint continuation remains an explicit, guarded action.
