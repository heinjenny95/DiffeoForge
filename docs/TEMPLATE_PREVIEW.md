# Native template projection preview

Status: **read-only orthographic inspection preview; not interactive 3D**

Desktop step 2 can render the selected template inside DiffeoForge without an
external viewer. The first slice deliberately uses native Qt painting and three
orthographic planes instead of introducing a heavyweight or platform-specific
3D dependency before the final rendering requirements are known.

## Source binding

The preview worker runs outside the GUI event loop and reuses the strict legacy
VTK PolyData parser. It records:

- the resolved template path and SHA-256;
- all immutable vertex coordinates and triangle indices;
- the exact six-axis bounds; and
- a sorted set of unique undirected triangle edges.

The file is hashed before and after geometry loading. A concurrent source
change, count mismatch, malformed VTK payload, non-triangular surface, invalid
index, or unreadable file discards the model. Projection changes never reread
the source; XY, XZ, and YZ views come from the same frozen model.

## Projection and display budget

Each plane is centered and normalized by the larger of its two coordinate
spans. The square QPainter viewport preserves that aspect ratio and flips only
the screen vertical axis. A plane with no finite two-dimensional extent fails
explicitly instead of drawing a misleading point.

The canvas draws at most 20,000 sorted unique edges. When the template contains
more, deterministic index-stratified selection supplies the display subset and
only their at most 40,000 endpoint coordinates are projected on plane changes;
full-mesh bounds remain the normalization reference. The GUI shows both
displayed and total edge counts. This limit protects GUI responsiveness; it is
not mesh simplification and never changes the source or any compute input.

## Interpretation boundary

The wireframe helps identify gross orientation, scale, and file-selection
mistakes. It does not provide:

- perspective or interactive 3D camera controls;
- hidden-surface removal, lighting, normals, or texture;
- landmark placement or coordinate editing;
- self-intersection, topology, or mesh-quality analysis;
- registration or atlas-result assessment; or
- biological interpretation.

Existing preflight and immutable mesh-QC evidence remain authoritative for
their declared checks. The separate 3D surface-landmark editor reuses the same
immutable geometry but has its own picking, persistence, and workflow tests; it
does not turn this inspection component into registration or QC evidence.
