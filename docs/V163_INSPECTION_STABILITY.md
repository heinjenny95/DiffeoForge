# Stable inspection layout

The complete-frame decision gate exposed a feedback loop in the styled review
window. Hiding its waiting hint freed vertical space for the 3D canvas. That
changed the exact frame key, invalidated the presented image and showed the hint
again. The resulting resize/render cycle could continuously disable decisions
and make a dense saved fit impractical to inspect.

The hint now retains its layout space while hidden. The existing decision panel
already reserves its space. Readiness can therefore settle without resizing the
canvas which established it. Rotation and zoom still disable decisions until the
matching complete frame is presented. Loading failures, source identity checks,
optional comparisons and recorded feedback remain unchanged.

Regression checks use the actual application stylesheet at three window sizes,
observe multiple event-loop/layout passes after readiness, require stable canvas
dimensions and render counts, and exercise navigation and decision recovery.
A separate read-only reproduction on a dense saved pair reproduced the former
cycle and verified that the corrected view settles. No optimizer was run.

This is a display-layout repair. It changes no geometry, fitted fields,
parameters, numerical thresholds or scientific approval. Rendering a complete
dense surface can still take time; the repair removes the repeated render loop,
not the cost of the first full frame. Installer delivery is tracked separately.
