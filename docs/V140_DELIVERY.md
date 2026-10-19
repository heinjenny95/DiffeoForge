# v140 Windows gallery repair

Runtime commit `0a563be` / version `0.0.0.dev140` is built and locally installed.
Later method documentation and optional-dependency test guards do not change the
runtime or require an identical installer rebuild. No Drive upload was requested.

## Package verification

The exact v139 PYZ/shared-runtime probe reproduces the missing PDF backend. The
equivalent exact v140 probe passes the actual renderer and Qt panel: 17 PNGs,
17 PDFs, three six-view MP4s (128 frames at 1260×840), ZIP integrity, all five
viewing tabs and decoded Qt video frames. Twelve synthetic inputs remain unchanged.
The mesh-PCA, SD, heatmap and 3D screenshots match source pixels exactly. All three
MP4 files are byte-identical between source and frozen output; Qt playback
screenshots differ. Only native sample generation is substituted in this probe.

All 33 pre-freeze focused cases passed. After the test-only optional-Matplotlib
guards, all ten media-runtime tests pass; deliberately blocking Matplotlib gives
the three expected skips in a minimal environment. Ruff and diff checks pass.

Installer SHA-256:
`76fe42342cd4c8d665376fe81d8d8c6811dd6aec6cdafbd46488d48c0e42eac2`
(466,189,246 bytes). This is a private local build, not a public release or a claim
of signing, scientific qualification or additional platform support.

## Local installation

A full hash-verified prior-runtime and project backup was rechecked after the
application closed. Windows and WSL guards found no relevant app/backend work.
The old installation remains recoverable. Silent installation returned zero;
all 3,473 installed bundle files, six evidence companions and registry version
match the tested build. Installed startup and PNG/JPEG/PDF/SVG/MP4 smokes pass.
All 11,531 existing project files and 11 protected atlas/PCA/endpoint files match
their baselines before reopening. The GUI was launched through the normal Windows
shell and its identity/ancestry verified again from an independent connection.

## Existing-result verification

The installed app reopened an existing completed result and generated its full
gallery through the normal UI. Independent checks pass for all source bindings,
the complete output inventory, PNG/PDF content, the presentation-only ZIP and
every frame of all three movies. All protected atlas/PCA/endpoint files remain
byte-identical; only derived display media and their native PC-path samples were
added. No atlas refit, PCA recomputation or review change occurred.

All five installed views display correctly: mesh PCA, mean/±2 SD, heatmaps,
six-view videos and PC1–PC3 3D. Qt video playback visibly advances through changing
geometry, and individual/gallery export controls are active. The app remains
open on the existing gallery. Private screenshots, manifests and verification
receipts remain with the local project, outside the public repository.
