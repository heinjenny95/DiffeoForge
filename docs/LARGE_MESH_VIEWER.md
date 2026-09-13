# Large-mesh desktop viewing

The result viewer and original/reconstruction QC overlay use background loading
and QImage rendering. This is a display-only change: atlas inputs, reconstructions,
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
- Only navigation frames are sampled: at most 1,500 solid triangles and 6,000
  original wireframe edges. Drag release and wheel settling request all faces and
  edges. This navigation aid is not evidence of scientific resolution equivalence.
- QC confirmation requires the current, fully rendered view to have been painted,
  with both overlay layers visible. Loading, navigation, errors and stale views
  cannot approve a case. Landmark clicks likewise require a full-resolution view
  at mouse press with unchanged camera/geometry at release. Exact surface picking
  continues to use the original geometry.

## Local engineering observation

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
Other loading paths and scientific computation are not accelerated by this fix.
The installed application needs a rebuilt binary and restart to use this code.

Regression coverage includes all-face rendering, caching, cancellation and
latest-view/selection races, worker failure, cached-artifact tampering, pending
and hidden-layer QC gates, safe landmark clicks, and existing release/draft rules.
