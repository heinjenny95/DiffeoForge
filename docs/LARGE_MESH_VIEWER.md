# Large-mesh desktop viewing

The result, calibration/QC, GPA, landmark and feature-ruler viewers use reduced
display geometry by default, including settled views. Heavy loading and 3D
QImage rendering run in background workers. This is a display-only change: atlas inputs, reconstructions,
landmarks, numerical analyses, QC thresholds and persisted review decisions are
not modified or decimated.

## Behaviour and safeguards

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
  separately for exact picking; a reduced model can never impersonate them.
- QC confirmation requires the current, fully rendered view to have been painted,
  with both overlay layers visible. Loading, navigation, errors and stale views
  cannot approve a case. Landmark clicks likewise require a full-resolution view
  at mouse press with unchanged camera/geometry at release. Exact surface picking
  continues to use the original geometry.
- Pilot visual-QC progress counts original-detail presentations, not merely opened
  proxies. The final pass/fail decision remains explicit. GPA proxies support an
  alignment review only, not approval of hidden anatomical detail; original aligned
  detail can be loaded separately. Orthographic original-vertex picking is disabled
  while a large reduced display is selected.
- Non-result preview loading has one active and one latest queued request, with
  stale results discarded; the landmark editor no longer retains a whole cohort
  of full meshes. GPA's shaded surface and cohort wireframes render in the shared
  background frame cache.

## Reduced-display observation

One private human mandible with 477,334 faces produced a 4,541-face display proxy
(270,264 bytes of display arrays). At 700 x 600 pixels the original frame took
3.55 s and the proxy 45 ms. Loading plus first simplification took 3.58 s, in a
separate engineering process. The side-by-side image was inspected and the source
SHA-256 remained unchanged. Teeth are visibly less detailed; this is precisely
why proxy viewing cannot stand in for original-detail QC or landmark picking.

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
