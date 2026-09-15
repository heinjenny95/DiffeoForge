# Large-mesh desktop viewing

The result, calibration/QC, GPA, landmark and feature-ruler viewers use reduced
display geometry by default, including settled views. Heavy loading and 3D
QImage rendering run in background workers. This is a display-only change: atlas inputs, reconstructions,
landmarks, numerical analyses, QC thresholds and persisted review decisions are
not modified or decimated.

## Behaviour and safeguards

- Landmark markers use the camera snapshot of the **displayed cached image**,
  not the latest requested camera. Image and camera are accepted together;
  rotation, pan, zoom and viewport resizing cannot move markers ahead of a
  background mesh frame. No markers appear before the first frame or after a
  specimen/cache clear. Failed/cancelled renders never advance the overlay camera.
  This fixes visual drift; saved world coordinates are not transformed or rewritten.
- Result geometry is verified and parsed outside the GUI thread. Only the latest
  selection may be displayed; rapid selection changes do not create a job backlog.
- An LRU geometry cache retains at most four models and one million aggregate
  faces (one oversize model is allowed). Even cache hits repeat manifest binding,
  containment, size and SHA-256 verification. QC approval repeats verification.
- Each canvas has one cancellable render, one latest pending view and one cached
  image. An unchanged view does not rasterize the geometry again. New specimens
  clear the old image immediately; pending camera views are visibly labelled.
- Default solid displays use at most 8,000 faces per mesh. Area-weighted face-plane
  quadrics determine representatives within spatial cells; clustered faces are
  connected, not uniformly discarded source triangles. The method is lossy and
  does not guarantee topology, tiny components, teeth or other small details.
  Source-bound proxy arrays are immutable and cached (16 entries / 16 MiB).
- Navigation is further bounded to 1,500 solid faces / 6,000 wireframe edges per
  layer. Settling keeps the selected display resolution, never silently restores
  a large full surface. Proxy-generation failure does not enable a full fallback.
- Original-detail inspection is an explicit slower option. It resets on specimen
  changes and invalidates the old frame. Original vertices/triangles are retained
  separately for picking and transfer; a display-only model cannot place landmarks.
- QC confirmation requires the current, fully rendered view to have been painted,
  with both overlay layers visible. Loading, navigation, errors and stale views
  cannot approve a case. Landmark clicks require the selected display frame to be
  presented at mouse press, with unchanged camera/geometry at release; reduced
  views are supported through original-surface transfer described below.
- Pilot visual-QC progress counts original-detail presentations, not merely opened
  proxies. The final pass/fail decision remains explicit. GPA proxies support an
  alignment review only, not approval of hidden anatomical detail; original aligned
  detail can be loaded separately. Orthographic original-vertex picking is disabled
  while a large reduced display is selected.
- Non-result preview loading has one active and one latest queued request, with
  stale results discarded; the landmark editor no longer retains a whole cohort
  of full meshes. GPA's shaded surface and cohort wireframes render in the shared
  background frame cache.

Regression `tests/test_landmark_frame_sync.py` checks actual painted landmark
pixels while an intentionally delayed renderer holds the old mesh frame, then
checks the replacement frame. Both reduced and original-detail modes cover
rotation, pan, zoom, resize and view presets; source arrays and marker coordinates
must remain unchanged. Picking and scientific QC still reject pending views.

## Reduced-display observation

One private human mandible with 477,334 faces produced a 4,541-face display proxy
(270,264 bytes of display arrays). At 700 x 600 pixels the original frame took
3.55 s and the proxy 45 ms. Loading plus first simplification took 3.58 s, in a
separate engineering process. The side-by-side image was inspected and the source
SHA-256 remained unchanged. Teeth are visibly less detailed; this is precisely
why proxy viewing cannot stand in for original-detail QC or fine anatomical
inspection. Alignment landmarks now support the explicit reduced-view transfer below.

These are single-view observations, not universal frame-rate, memory or anatomical
accuracy guarantees. Reproduce with `tools/benchmark_display_proxy.py`, writing
private output outside the repository. No additional native simplifier dependency
or source mesh repair/decimation is introduced.

A follow-up native-event-loop observation loaded and first displayed the same
mesh in 3.71 s while a 10-ms GUI timer fired 254 times (median interval 10 ms,
maximum gap 0.66 s). Source hash and original-picking lock were preserved. This
ran alongside build/test work and shows remaining short stalls, not zero-latency
interaction. The new private build is documented in
`NEXT_VERSION_BUILD_2026-09-14.md`; it has not been installed.

## Reduced-view alignment landmarks (15 September 2026)

Landmark placement no longer requires switching each specimen to Original detail.
The click first intersects the frontmost triangle of the actually displayed proxy.
A background, cancellable nearest-surface search then transfers that 3D location
to the unchanged original triangles, including face interiors and edges, not only
vertices. Temporary arrays cover at most 32,768 source triangles at a time. The
full original is not rendered to place the point. Original-detail clicks retain
direct surface intersection.

The displayed frame must be settled and current at press and release. Pending
transfers are invalidated on mesh/label changes, undo/clear, resolution changes,
neutral-view mode and editor closure. Failed transfers show an error rather than
storing a proxy coordinate. Save waits for a pending replacement; autosave,
auto-advance, undo and CSV export keep original-coordinate behaviour. A proxy-only
model without original geometry remains unpickable. Full-detail QC gates are
unchanged.

This is approximate anatomical placement for alignment, not recovery of hidden
detail or proof of landmark homology. On thin, nearby or overlapping surfaces,
the nearest face can differ from the intended anatomical feature. Inspect Original
detail when necessary. Original meshes, source hashes and existing points are not
modified.

Verification: 132 targeted tests passed, with one environment-specific skip,
covering displaced proxies, surface interiors/edges, translated and scaled source
coordinates, background execution, stale-result rejection, consecutive specimens,
real Qt editor clicks, autosave and CSV export, plus existing rendering/QC tests.
A separate 200,000-triangle synthetic nearest-surface query took 0.068 s on the
development workstation; this is a kernel observation, not an end-to-end latency
or anatomical-accuracy guarantee. No private study data was used in these tests.

The user-authorized local Windows CPU update was built from `3f31712` and
installed on the same day. All five Python modules changed since the previous
installed runtime matched their embedded bytecode; 27 isolated landmark tests
also passed against the embedded modules. Frozen startup, public synthetic Modern
execution, reference preparation, cancellation and parent-death checks passed.
All 2,676 installed bundle files were hash-verified, the startup smoke exited 0,
and the desktop shortcut targets the updated EXE. Its SHA-256 is
`174c37296e615f41b07528c0d878ef5bbffcbe395b7aa6dc211bcf1927588836`.
The previous 2,687 application files were backed up and hash-verified; the user's
landmark draft was separately preserved. This is an unsigned local test build,
not a public release or scientific validation. Private data, installers and
backup paths remain outside GitHub.

## Synthetic size/viewer matrix (15 September 2026)

All nine 10k/100k/200k-face observations completed using the three production
canvas families and native offscreen Qt event loops. At 200k, sampled navigation
frames took approximately 30–80 ms; the explicit original-detail QC pair took
2.38 s and incurred a maximum 0.49 s GUI-timer gap. Default displays stayed below
8k faces, source hashes were unchanged, and proxies could not satisfy
original-detail QC readiness. These are observations, not latency guarantees.

The installed Windows landmark editor also passed a bounded 200k-face check:
rotate, next specimen, original detail, close and reopen into a fresh proxy.
No landmark draft or project was saved. The GPA legend now follows all three
layer switches in source; the installed `063143a` binary remains unchanged.

See [the retained matrix](../reference/desktop-viewer-matrix-v1/README.md) for
timings, memory interpretation, public synthetic screenshots and reproduction.
The shared QC/PCA surface canvases were exercised, not full installed result-bundle
opening, new PCA calculations or anatomical defect-detection accuracy.

## Installed completed-result check (15 September 2026)

A fresh instance of the unchanged installed Windows runtime `063143a` opened an
existing completed 100-subject human-mandible run through **Open completed run**.
Its existing PCA bundle and finalized flagged-case review were verified; no atlas,
Validation Lab, PCA calculation or PC-shape Shooting job was started.

The full pre-viewer verification took approximately **11 minutes**. Periodic
process observations reached a working set of **6,421,585,920 bytes (5.98 GiB)**;
after verification it fell to approximately 447 MB. These are one-run,
coarse-grained observations, not exact peak-memory or controlled latency
benchmarks. The process remained responding during the probes and did not crash.

Installed UI checks passed:

- Atlas-template display and rotation: 229,324 source faces, 4,430-face display
  proxy.
- Two flagged-case overlays, rotation, original-detail rendering and hiding the
  original layer. One pair contained 246,464 original and 229,324 reconstructed
  faces; its reconstruction display proxy contained 5,027 faces.
- Switching specimens cleared the previous geometry while loading and reset to
  proxy display with both layers visible. Proxy/pending/hidden-layer views could
  not confirm inspection; original-detail readiness enabled the inspection
  checkbox, but it was deliberately left unchecked.
- Existing scree, PC1-versus-PC2 and PC2-versus-PC3 plots, plus QC/results page
  re-entry in the same session. The existing 9 approved flagged cases and 91
  unreviewed cases remained unchanged; all 100 specimens remained included.

Before/after inventories matched every path, size and SHA-256 for **1,269 files
(10,616,332,159 bytes)**, with no additions or removals. The installed EXE hash
also remained unchanged. Private meshes, screenshots, inventory hashes and local
paths are not published. The application was left open at the verified results.

The check exposed an unrelated loading-status defect: the empty setup page
displayed missing-input errors while completed-run verification was active.
The source fix keeps an engine-specific verification message and busy button
caption visible through form refreshes, explicitly stating that no atlas is being
recomputed. The targeted desktop/release/result/rendering suite passed **104
tests, with 2 environment-specific skips**; Ruff and whitespace checks passed.
This fix is source-only and does **not** accelerate full-run verification.

Next: profile full-run verification, including QC metric collection that currently
retains all reconstruction meshes. Bound memory and report truthful stage progress
without weakening artifact verification or changing scientific QC definitions.
This check did not repeat the large-run open after an application restart, exercise
rapid selection races in the installed app, or test generated PC endpoint meshes
(none existed in this run). It is an engineering smoke test, not anatomical QC
approval or scientific validation. Synthetic lifecycle/race coverage remains
separate evidence above.

## Earlier full-frame-cache observation (before default proxies)

One private completed-atlas pair (246,464 original faces; 229,324 reconstructed
faces) was measured offscreen at 1,000 x 600 pixels on the development workstation.
Baseline source: `c6b875657d2e54a7401a01d664759b1c9eff2351`.

| Operation | Observed time |
| --- | ---: |
| Parse the full pair | 3.32 s |
| Previous full repaint of an unchanged view | 3.82 s |
| New full frame, in background | 2.96 s |
| New cached repaint, median of 30 | 0.69 ms |
| New navigation frame | 33.61 ms |
| GUI geometry-array installation | 227 ms |

A 10-ms GUI timer continued firing during the background frame (145 callbacks;
median interval 15.86 ms, maximum 386.35 ms). This demonstrates responsiveness,
not a hard latency or frame-rate guarantee. Measurements used a native Qt event
loop; a tight `QTest.qWait` loop can starve Python render workers and is not a
representative rendering benchmark. Baseline and new settled PNGs were byte
identical for this view; both mesh hashes were unchanged. Private meshes, PNGs
and local paths are intentionally excluded from this repository.

The first full view still takes seconds. Rendering remains CPU-based, not GPU
rasterization; Python work and array installation can still cause brief pauses.
At that earlier stage, other loading paths were not accelerated. Scientific
computation remains unchanged by either viewer update.
The installed application needs a rebuilt binary and restart to use this code.

Regression coverage includes all-face rendering, caching, cancellation and
latest-view/selection races, worker failure, cached-artifact tampering, pending
and hidden-layer QC gates, safe landmark clicks, and existing release/draft rules.
Asynchronous registration tests wait in Qt's native event loop instead of a tight
`QTest.qWait` polling loop, which caused a timeout under concurrent build load.

## Earlier private Windows build (does not include default proxies)

Runtime commit `d4096a62e5a1d17542d6ead7f03d27dd2bebe079` was frozen locally.
GUI startup, synthetic Modern execution, reference/preparation worker smokes,
cancellation/parent-death checks, and the 2,676-file bundle inventory passed.
Seven embedded viewer/QC modules were compared to compiled source and matched
exactly. The unsigned same-owner installer was packaged and verified, not
installed or publicly released. Later test-wait/documentation hardening does not
change the runtime in that installer. Installation and application restart remain
an explicit next step; existing study data and QC drafts were not changed.
