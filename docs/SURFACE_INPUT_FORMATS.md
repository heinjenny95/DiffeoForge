# Surface input formats for landmark preprocessing

Status: **tested desktop landmark/GPA import path; atlas engines remain
canonical-VTK consumers**

DiffeoForge accepts triangular legacy VTK PolyData, PLY, Wavefront OBJ, and STL
as source surfaces for desktop inspection, homologous landmark placement, and
reviewed generalized Procrustes preprocessing.

## Deliberate two-directory output

Approved preprocessing publishes one content-addressed directory:

```text
preprocessing/aligned-<fingerprint>/
  raw/
    template.obj
    subject-01.ply
    subject-02.stl
  aligned-vtk/
    template.vtk
    subject-01.vtk
    subject-02.vtk
  landmarks.csv
  procrustes.json
```

`raw/` contains byte-identical copies with their original names, formats, and
SHA-256 values. `aligned-vtk/` contains deterministic ASCII legacy VTK triangle
surfaces after the approved similarity transforms. Both the Deformetrica and
Modern routes consume only `aligned-vtk/`. DiffeoForge does not also write
transformed PLY, OBJ, and STL variants: one canonical downstream representation
avoids several numerically identical but provenance-ambiguous products.

`procrustes.json` binds every source filename, format, encoding, raw-copy path
and hash, canonical output path and hash, geometry count, transform, residual,
landmark file, settings, convergence history, and exact preview fingerprint.
The source folder itself is never modified.

## Supported subsets

- **VTK:** ASCII or big-endian binary legacy triangular PolyData already
  supported by the atlas workflows.
- **PLY:** format 1.0 ASCII, binary little-endian, or binary big-endian;
  scalar vertex properties must include `x`, `y`, and `z`; face indices must
  be an integer `vertex_indices` or `vertex_index` list.
- **OBJ:** UTF-8 text with `v` vertices and `f` faces; positive and negative
  vertex references and the standard `v/vt/vn` spelling are accepted.
- **STL:** ASCII or exact-length binary little-endian triangle facets. Because
  STL has no shared vertex index, identical facet coordinates are
  deterministically deduplicated before landmarking and VTK output.

All inputs must contain exclusively triangular faces. PLY or OBJ polygons are
rejected rather than silently triangulated, because a hidden triangulation
choice would change topology. Normals, colors, texture coordinates, materials,
and other non-geometric properties are ignored and are not copied into the
canonical VTK product. Units are still declared explicitly by the researcher;
no supported format is treated as a reliable unit source.

## Workflow boundary

PLY, OBJ, and STL are accepted only when a landmark CSV is selected or created,
generalized Procrustes is enabled, and the exact read-only preview is approved.
Without that reviewed conversion, project setup remains VTK-only. This keeps
format conversion visible and prevents a non-VTK mesh from reaching an engine
through an undocumented implicit operation.

Format support establishes readable geometry and reproducible conversion. It
does not establish biological landmark homology, acceptable registration,
mesh repair, self-intersection freedom, or scientific suitability.
