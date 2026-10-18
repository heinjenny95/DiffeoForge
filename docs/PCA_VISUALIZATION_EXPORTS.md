# PCA mesh plots, endpoint heatmaps and axis movies

These are requirements for reproducible derived media, not an installed feature
or a replacement for atlas/PCA verification and human anatomical review. Keep
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
endpoint selection still needs a separate repair and regression/installed checks.

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
generation beneath the PCA plots remains a separate open product backlog item.

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
