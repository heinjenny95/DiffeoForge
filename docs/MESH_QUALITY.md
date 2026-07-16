# Deterministic mesh-quality evidence

Status: **implemented engineering gates; not a complete surface-validity test**

Tracked prospectively by
[scientific-change issue #32](https://github.com/heinjenny95/DiffeoForge/issues/32).

## Why this exists

A readable triangular VTK file is not necessarily suitable atlas input, and an
output with the expected number of points and faces can still be degenerate.
DiffeoForge therefore measures the exact meshes used by `modern-run`, applies
explicit gates before optimization, and assesses every generated template,
reconstruction, and PCA endpoint before publication.

The implementation is dependency-free and deterministic. JSON retains the
complete evidence; CSV exposes a stable review table. The run and bundle
verifiers recompute both artifacts from the VTK geometry rather than trusting
stored values or hashes alone.

## Exact definitions

All topology is computed from the ordered triangle index array. An undirected
edge is the sorted pair of its endpoint indices.

- boundary edge: incident to exactly one face;
- manifold edge: incident to exactly two faces;
- non-manifold edge: incident to three or more faces;
- orientation inconsistency: the two faces of a manifold edge traverse it in
  the same direction;
- duplicate face: an additional face with the same unordered vertex triple;
- isolated vertex: a point index referenced by no face;
- face-connected component: a component under shared-undirected-edge
  adjacency;
- Euler characteristic: `points - unique_edges + triangles`, reported without
  inferring genus;
- triangle area: half the Euclidean norm of the cross product;
- edge ratio: longest divided by shortest edge within one triangle;
- minimum angle: the smallest non-oriented internal triangle angle;
- local face-area ratio: output triangle area divided by the corresponding
  triangle area of the final estimated template, requiring identical ordered
  connectivity.

Metric summaries contain minimum, 5th percentile, median, mean, 95th
percentile, and maximum. Quantiles use linear interpolation at sorted index
`(n - 1) * q`; this rule is part of the report and prevents library-version
defaults from silently changing results.

These operational definitions are intentionally narrower than a general mesh
repair or validity library. For context, VTK distinguishes boundary and
non-manifold edges in
[`vtkFeatureEdges`](https://vtk.org/doc/nightly/html/classvtkFeatureEdges.html)
and publishes triangle quality measures in
[`vtkMeshQuality`](https://vtk.org/doc/nightly/html/classvtkMeshQuality.html).
CGAL separately documents polygon-mesh orientation, manifold constraints, and
repair operations in its
[`Polygon Mesh Processing` package](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html).
DiffeoForge does not silently repair a mesh.

## Configuration and gates

`modern-init` writes every decision into `quality_control`:

```yaml
quality_control:
  require_no_duplicate_faces: true
  require_no_isolated_vertices: true
  require_edge_manifold: true
  require_consistent_orientation: true
  require_single_component: false
  require_closed_surface: false
  reject_zero_area_faces: true
  minimum_triangle_angle_degrees: null
  maximum_triangle_edge_ratio: null
  minimum_face_area_ratio: null
  maximum_face_area_ratio: null
```

Open surfaces and multiple disconnected anatomical parts are not rejected by
default because both can be legitimate study designs. Numeric thresholds are
`null` by default because defensible cutoffs depend on acquisition,
simplification, scale, anatomy, and model settings. A paper or study protocol
should predeclare any enabled numeric thresholds and justify them independently
of the observed outcome.

Structural gates apply to raw inputs, effective inputs after optional
Procrustes alignment, and all bundle meshes. Local face-area ratio gates apply
to reconstructions and PCA endpoints relative to the final estimated template.
Any failure aborts atomic creation: no partial run or bundle is published.

## Evidence locations

The outer workflow contains:

```text
quality/input-mesh-quality.json
quality/input-mesh-quality.csv
```

Every template and subject has separate `raw` and `effective` records. Without
alignment both stages intentionally point to the same immutable copy; retaining
both records keeps the processing contract stable.

The nested result bundle contains:

```text
quality/mesh-quality.json
quality/mesh-quality.csv
```

It covers the estimated template, every subject reconstruction, the mean-
momenta mesh, and each emitted positive and negative PCA endpoint. Report and
CSV files are included in the exact artifact inventory and SHA-256 chain.
Text cells beginning with spreadsheet formula characters receive a leading
apostrophe in CSV; exact labels remain unchanged in JSON.

## Scientific boundary

The current assessment does **not** detect triangle-triangle
self-intersections, non-manifold vertices whose incident edges are individually
manifold, global embedding validity, anatomical plausibility, registration
quality, or Deformetrica equivalence. It also does not prove topology
preservation throughout the continuous deformation path; it assesses the
stored endpoint meshes. Rendering and interactive inspection remain future
work.
