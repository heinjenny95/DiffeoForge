# High-resolution mesh intake

DiffeoForge does not treat a large mesh as scientifically defective. Fine surface
detail can be the object of a study, and a small cohort of dense meshes can be a
reasonable workload. Input policy is therefore based on the combined atlas workload,
not on a universal per-mesh face limit.

## Source, display, and computation are separate

DiffeoForge keeps three responsibilities distinct:

1. **Source meshes** remain byte-identical, read-only inputs whose hashes and geometry
   metadata are recorded.
2. **Display proxies** are deterministic, bounded subsets used only by the interactive
   GPA review. The current desktop budget is 8,000 source triangles per displayed
   mesh. The dialog labels this explicitly and reports the full-resolution source
   workload.
3. **Scientific computation meshes** retain the complete input geometry. Landmark GPA,
   exact topology checks, Deformetrica, and the Modern Engine do not consume the display
   proxies. DiffeoForge never silently decimates an analysis mesh.

The proxy preserves only the selected source faces and their referenced vertices; it
does not claim to be a watertight reconstruction or a scientific resampling. Its sole
purpose is responsive visual review of the landmark-derived transforms.

## Local memory behavior

The asynchronous input preflight reports per-mesh progress and computes exact topology
with compact edge bookkeeping and union-find face components. It still parses every
surface, because non-manifold edges, duplicate faces, boundary edges, orientation, and
connected components cannot be inferred reliably from file size or a sparse preview.

Approved preflight metadata are reused by the numerical GPA preview. Project creation
then verifies the approved preview and processes one full-resolution mesh at a time:
copy the immutable source, load it, apply the approved similarity transform, write the
canonical aligned VTK, record evidence, and release it before loading the next mesh.
It no longer retains the complete cohort twice in memory. The ASCII VTK writer also
streams output instead of first building duplicate normalized geometry and a complete
in-memory text document.

These changes bound retained cohort geometry, but they do not make parsing one single
mesh free. The client must still have enough memory for its largest individual mesh and
for exact quality metrics. Very large ASCII PLY files also retain their inherent parsing
cost.

## Scale and units

Landmark GPA with centroid-size scaling removes one similarity scale per specimen from
both its landmarks and its mesh. Raw size groups are therefore not automatically unit
errors. The fail-closed condition is different: the landmark configuration and the mesh
for the same specimen must share a coordinate frame, otherwise the landmark-derived
transform would be invalid for that mesh.

When GPA scaling is disabled, size groups remain advisory because geometry alone cannot
distinguish biological size, acquisition units, life stages, or previous preprocessing.

## Server execution boundary

The Modern Engine already supports an explicit private authenticated server route with
request verification, persistent queueing, reconnectable progress, cancellation, and a
verified result download. Display-proxy and sequential-GPA preparation reduce the local
front-end burden before that hand-off, but preprocessing is still performed locally and
the current remote service is Modern-only.

Production support for datasets that cannot fit even one source mesh on the client still
requires additional engineering: streamed or isolated-process parsers, resumable
content-addressed upload, server-side preprocessing with identical evidence semantics,
and a qualified institutional deployment. Those features must preserve the rule that
analysis resolution changes are explicit, versioned scientific decisions rather than
automatic performance fixes.
