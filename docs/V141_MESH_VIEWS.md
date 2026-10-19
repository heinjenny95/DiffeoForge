# v141 — choose the relevant surface in PCA plots

The previous 3D morphospace rotated very coarse specimen geometry with the PCA
camera. Useful anatomical surfaces could face away; rendering successfully did
not establish that the view was useful. Stage 7 now separates these two choices.

**Mesh view…** opens a large specimen preview. Choose any specimen, start from
one of six opposing coordinate views, then drag or adjust Turn, Tilt and Roll.
Name the view and apply it to all specimens. Users choose what matters for their
data; a coordinate direction is never automatically labelled as an anatomical
surface. Multiple named views are saved beside the result's media cache and bound
to its manifest identity. Cancelled previews do not change the applied view.

The 2D and 3D PCA plots share detailed rendered specimen images. In 3D these are
image glyphs, rather than independently rotatable mesh objects: rotating the PCA
camera changes score projection while the chosen anatomical view stays facing
the reader. All specimens use one camera, cohort bounds and world-to-image scale.
Mesh-size controls do not move saved scores. The 2D selector includes all three
PC1–PC3 pairs; the 3D camera can still rotate, pan, zoom and select specimens.

Display surfaces are read from exactly one inventoried reconstruction per saved
subject and checked against source size/hash, common topology and exact score
rows. A common topology-preserving display proxy targets 20,000 triangles and
retains exact source vertex IDs; topology constraints may retain more triangles.
Rendering runs on one background worker with cancellation and a latest-request
queue. A complete new set replaces the old images together. The original atlas,
PCA, checkpoints, scientific approvals and sealed media remain unchanged.

Current PNG/JPEG snapshots retain the selected view. A gallery ZIP exported after
applying a view rebuilds its PCA thumbnails and three PNG/PDF plots, records the
view rotation, and keeps exact score positions. Existing SD panels, displacement
maps and movies retain their labelled cameras. Raw geometry, logs and checkpoints
are not added to the presentation archive. No network sharing is implicit.

## Verification and remaining scope

Focused checks cover camera validity, source/score tampering, common scale,
cancelled/stale requests, persistent view identity, independent 3D camera motion,
orientation-aware ZIP export and preserved originals. Source, exact frozen
runtime, installation and independent first use are separate checks; delivery
evidence records their actual state. No anatomical choice is approved by these
engineering tests.

The final focused source run passes 37 cases with clean process exit. A synthetic
Qt preview, shared 2D/3D view, saved-view restore and three-pair PNG/PDF/ZIP probe
also passes. Frozen/installed delivery verification is recorded separately.

The new controls cover Stage 7's atlas PCA glyphs. Other comparison-method viewers
retain their existing controls. Reusing named views across SD panels, maps,
movies and comparison methods, with optional crop/focus and an export preview,
remains a follow-up. Those outputs need their own cache identity and common-scale
checks before claiming that every medium follows a project view.
