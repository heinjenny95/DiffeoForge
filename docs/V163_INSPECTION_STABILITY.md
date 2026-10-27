# Stable inspection layout

## Preview decisions, optional full detail

The owner explicitly prefers reviewing the display previews. A matching settled
preview of the original and reconstruction is sufficient to approve, reject or
give relative feedback. Complete geometry is loaded only on an explicit detail
request; the first preview no longer automatically starts a complete-mesh load.
Selected saved alternatives also use the source-bound preview cache. A failed
optional detail request preserves the usable preview and its decision route.

Source path/hash, selected-attempt identity, both visible layers, a nonempty
rendered image and settled navigation remain required. A blank image cannot
qualify merely because source models were loaded. Original-bound problem-area
selection still resolves the original geometry when the user explicitly opens
that operation; this is separate from approving the preview.

## Stable layout

The complete-frame decision gate exposed a feedback loop in the styled review
window. Hiding its waiting hint freed vertical space for the 3D canvas. That
changed the exact frame key, invalidated the presented image and showed the hint
again. The resulting resize/render cycle could continuously disable decisions
and make a dense saved fit impractical to inspect.

The hint now retains its layout space while hidden. The existing decision panel
already reserves its space. Readiness can therefore settle without resizing the
canvas which established it. Rotation and zoom still disable decisions until the
matching selected frame is presented. Source identity checks and recorded
feedback remain unchanged; optional detail failures permit preview assessment.

Regression checks use preview and full geometry with the actual application stylesheet at three window sizes,
observe multiple event-loop/layout passes after readiness, require stable canvas
dimensions and render counts, and exercise navigation and decision recovery.
A separate read-only reproduction on a dense saved pair reproduced the former
cycle and verified that the corrected view settles. No optimizer was run.

This changes display review policy and layout. It changes no geometry, fitted fields,
parameters or numerical thresholds and grants no scientific approval. Rendering a complete
dense surface can still take time; the repair removes the repeated render loop,
not the cost of the first full frame. Installer delivery is tracked separately.
