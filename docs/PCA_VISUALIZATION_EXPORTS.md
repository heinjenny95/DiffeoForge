# PCA mesh plots, endpoint heatmaps and axis movies

v129 implements the integrated source route described in [its scope](V129_PILOT_AND_VISUALIZATION.md).
Frozen/installed verification remains separate. The requirements below retain the
original media/interpretation contract. Atlas/PCA verification and human
anatomical review remain separate. Keep
private study files, specimen identifiers and local paths outside this public
repository. Deliver media alongside the original project, with a private source
manifest and file hashes.

## Mesh plots

Place each reconstruction at its saved PCA score coordinates. Use the same mesh
orientation, camera and world-to-image scale across specimens; do not jitter
coordinates or resize each specimen independently. State the explained variance
on each axis. Keep a specimen key and provide zoom or glyph-size controls when
meshes overlap. Topology-preserving display proxies are acceptable when explicitly
labelled and bound to their full-resolution sources.

## PC shapes and native integration

For score coordinate `s`, shoot `mean_momenta + s * sqrt(variance) * PC_loading`
from the saved template and control points. The mean shape is the shape shot at
the mean momenta, not the arithmetic mean of reconstructed surface vertices.
The +/-2 SD shapes are model-derived PC-axis examples, not observed specimens
or biological limits. Preserve the fitted atlas, PCA, original exports and reviews.

Verify the *effective* native integration grid and the exported physical time,
not just an XML setting or an output filename. A local inspection of the native
Deformetrica 4.3.0 Shooting route found that `number_of_timepoints` did not set the
Geodesic concentration used by that route. Its default produced 11 points over
`[0,1]`; choosing `tp_9` from a declaration of 10 therefore selected `t=0.9`.
An endpoint export must establish `t=1` explicitly and record the actual grid,
native precision and initial momenta. A run-scoped display adapter can do this
without changing native equations or existing runtime files. Existing application
endpoint selection is repaired in v129 source with v0.2 native grid receipts;
legacy exports remain unchanged and installed checks are tracked separately.

## Heatmaps

Measure corresponding-vertex displacement from the shot mean on verified shared
topology. Export the displacement vector, its magnitude, and optionally its signed
component along the consistently oriented mean-surface normal. Label the latter
as a normal component, not volume change. Use a shared scale across PC axes and
signs, with fixed cameras and no unreported registration. Report normalized units
when preprocessing removed physical scale; do not label normalized coordinates as
micrometres. State whether summary statistics use vertex or surface-area weights.

## Movies

Show each PC independently from -2 SD through the mean to +2 SD, with visible
axis/score labels and fixed camera, mesh scale and heatmap range. Use native
Shooting samples along the PC coordinate. If playback interpolates corresponding
vertices between adjacent samples, record the sample spacing and interpolation
policy; do not present this as an optimization trajectory. Verify display-proxy
anchors against the full-resolution endpoints, and decode the delivered videos
to check frame count, rate, dimensions and actual geometry change.

Show multiple synchronized views simultaneously so a change on the far side of
the surface is visible. A complete orthographic layout pairs the two opposing
directions for each coordinate plane: XY from +/-Z, XZ from +/-Y and YZ from
+/-X. Keep the same score in every panel and label viewing direction with an
orientation glyph. Preserve aspect ratios, match camera scale across axes and
frames, and verify opposite camera vectors and visible change in each view.
This view requirement follows owner feedback about occluded PC-axis changes;
it does not establish an anatomical interpretation or an installed UI change.

Keep scripts, dependency versions, grid receipts, source immutability checks,
measurement definitions and final hashes with the private delivery. Automatic
generation beneath the PCA plots is implemented in v129 after verified result
release; independent usability acceptance remains separate.

## Media-only sharing export

For an owner-requested colleague handoff, provide a portable offline gallery with
short English media headings and relative asset links. Include the selected
figures/PDFs, current synchronized-view movies and an optional interactive plot.
Keep detailed provenance, logs, scripts, checkpoints, raw meshes and identity keys
in the private project rather than the presentation package. Numeric plot IDs
may remain. Verify media copies, local links and every ZIP member against hashes;
retain the verification receipt alongside the original private delivery. Creating
the export does not authorize sending it or uploading it to a public service.
After explicit upload authorization, verify the complete uploaded bytes against
the local export and check the requested file-specific read-only link scope.
Keep file IDs, URLs and verification receipts in the private project; preserve
other files' permissions and the separately tracked installer distribution.

## Deferred follow-up — 19 October 2026

The initial request was a backlog entry; the owner later authorized implementation.
v138 adds the 3D view and individual exports below. Step 6 also displays saved
comparison-method results with selectable axes, PNG/JPEG export and an optional
mesh-based 3D view when at least three dimensions were saved. Method labels retain
PC, kPC, PCo, Dim or DC as appropriate; nonlinear embeddings do not acquire invented
variance percentages or native PC deformations. See [v138](V138_DESKTOP_BACKLOG.md).
Source checks, frozen delivery and independent first use remain separate gates.

- [x] **Interactive 3D morphospace.** Show PC1, PC2 and PC3 together, placing
  miniature specimen meshes at their existing verified score coordinates.
  Support rotation, pan, zoom, reset view, specimen selection/hover with score
  values, and glyph-size adjustment for overlap. Keep axis names and explained
  variance visible. Use common mesh orientation/scale and appropriately bound
  display proxies; changing glyph size must not move the PCA positions. Handle
  results with fewer than three usable PCs explicitly. Cache/preload display
  geometry with bounded background work; no atlas refit or PCA recomputation.

- [x] **Direct export of every displayed medium.** Allow individual saves for
  mesh-PCA plots, mean/minus/plus SD panels, heatmaps and each available movie.
  Add an image snapshot of the 3D morphospace using its current camera, distinct
  from an export that retains interactivity. Use **PNG** as the default lossless
  image format, optional **JPEG**, and **MP4** for video. Keep existing **PDF**
  figures and the complete gallery **ZIP**; do not make ZIP the only save route.
  Clearly distinguish current-item export from exporting all media. Preserve
  aspect ratios, legends, score/axis labels, units and shared color scales; expose
  useful output-resolution/quality choices without adding routine technical prose.
  Reuse matching verified assets and validate the saved images/video decoding.
  Keep source scientific artifacts intact and preserve the media-only package
  boundary: no automatic inclusion of raw mesh geometry or checkpoints.

Implementation starting points:
[Step 7 panel and existing ZIP export](../src/diffeoforge/desktop/visualization_panel.py),
[prepared media/gallery pipeline](../src/diffeoforge/pca_media.py).
Interacting with mesh glyphs and maintaining responsiveness across representative
cohort sizes need explicit engineering checks; reusing PCA coordinates alone
does not establish that acceptance.

## Prepare results before converged atlas completion — pending

Owner request, 19 October 2026: point plots are available first, while the other
results still need preparation. Move that preparation into the final export and
postprocessing phase so a completed workflow has its configured results ready.
This is a new backlog item, not an implemented v138 behavior or verification of
the owner's reported completed run.

- Trigger automatic preparation only after the backend explicitly reports native
  convergence, return code zero and consistent verified terminal/export metadata.
  Reaching an iteration cap, cancelling, interruption or failure must not trigger
  it. Do not infer convergence from appearance, a flat plot or a successful export.
- Prepare results for the configured analysis scope and every supported applicable
  view: saved method results, mesh morphospace plots, display geometry for optional
  interactive 3D, mean/SD panels, endpoint heatmaps and axis movies. Preserve each
  method's existing dimensionality and deformation semantics; do not invent native
  PC deformations for methods that do not support them. Do not silently enable
  additional scientific analyses or replace prior results.
- Run bounded background work during export/postprocessing with clear progress.
  Distinguish **Optimizer converged**, **Preparing results** and **Results ready**;
  report overall completion only when the required configured assets are verified.
  Optional or failed assets need a concise availability/error state and a targeted
  retry, without relabeling numerical convergence or repeating the atlas fit.
- Reuse only verified assets bound to the same source result, subject order,
  method, settings and geometry. Seal sizes/hashes and validate image/video
  decoding before publishing readiness; preserve original scientific artifacts.
- Opening Steps 6 and 7 after completion should use the prepared results and
  caches without another expensive analysis/render preparation pass. Ordinary
  interactive camera drawing may remain on demand. Numerical convergence never
  substitutes for anatomical approval or interpretation.
- Verify the trigger/non-trigger paths, preparation failure/retry, stale-cache
  rejection, responsive progress and direct access to every applicable prepared
  result after reopening the completed project.
