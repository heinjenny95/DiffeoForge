# Landmark-based Procrustes alignment

Status: **tested engine-independent preprocessing integrated into Modern and
Deformetrica project setup, with interactive 3D triangle-surface placement and
hash-validated resumable drafts in the desktop**

Tracked by [scientific-change issue #18](https://github.com/heinjenny95/DiffeoForge/issues/18).

## Purpose and order of operations

The implemented workflow is:

1. record the same ordered homologous landmarks for every specimen;
2. use the landmarks to estimate and preserve translation and orientation;
3. apply the explicitly selected mesh-size policy and the landmark-derived rigid
   transform to every vertex of the complete mesh;
4. run the atlas on the aligned mesh copies while retaining the raw meshes;
5. compute downstream statistics in an explicitly named feature space.

Alignment is therefore a separate preprocessing decision, not an invisible
side effect inside an atlas engine.

## Implemented mathematical contract

`diffeoforge.analysis.generalized_procrustes` accepts a float64 array with shape
`(subjects, landmarks, 3)`. Landmark index is the homology contract: changing
the order changes the scientific meaning of the analysis.

For each specimen the prototype:

- subtracts the landmark centroid;
- divides the landmark configuration by centroid size while estimating orientation;
- estimates a least-squares orthogonal rotation with SVD;
- prohibits reflections by default;
- iteratively updates a centered unit-centroid-size landmark consensus.

The final scale applied to the complete surface is a separate scientific choice:

- **Shape only — surface scale, resolution-independent (default):** divide by the
  area-weighted RMS radius of the triangular surface. Integrating triangle moments
  makes this measure invariant to subdivision of an unchanged piecewise-linear surface.
- **Shape only — published PAMS:** divide by complete-mesh vertex centroid size. This
  reproduces the alignment/scaling definition used by Roberts et al. (2026), but can
  vary with vertex sampling density. Selecting this desktop preset also selects the
  paper's common working size of 1000; both values remain explicit and editable.
- **Size + shape:** apply translation and rotation while preserving specimen size.
- **Legacy landmark scale:** divide the entire mesh by landmark centroid size. This is
  retained for exact reproduction of earlier DiffeoForge projects, not as the new default.

All size-removing modes expose an arbitrary common working-size constant. Changing it
changes absolute atlas widths and noise values, so pilot calibration must be repeated.

Each returned `SimilarityTransform` stores the original centroid, applied scale
factor, and 3 × 3 rotation. With row-vector coordinates, its forward mapping is

`aligned = ((raw - centroid) * scale) @ rotation`.

The same transform can be applied to the full mesh and inverted. Returned
consensus/landmark/transform arrays are read-only copies, so later input edits
cannot silently rewrite the evidence.

## Validation and failure policy

Tests recover known translations, rotations, and scales; apply transforms to
full-mesh vertices and round-trip them; distinguish proper rotations from
explicitly enabled reflections; preserve size differences when scaling is
disabled; and verify same-runtime repeatability and input non-mutation.

The prototype rejects non-float64, non-finite, wrongly shaped, duplicate, and
collinear landmark configurations. At least two subjects and three distinct
non-collinear landmarks per subject are required. It records every consensus
update, mean change, total squared residual, convergence flag, and termination
reason.

## Workflow integration and scientific limitations

The shared preprocessing layer uses a strict canonical long-form CSV with
`mesh_file,landmark,x,y,z`, requires identical ordered labels for the template
and every subject, reads triangular VTK, PLY, OBJ, or STL source surfaces,
writes transformed full-mesh copies in one canonical VTK representation, and
inventories the complete transformations and convergence evidence. Raw meshes
are never edited. A content-addressed publication separates byte-identical
original-format files under `raw/` from transformed products under
`aligned-vtk/`. Content-addressed aligned cohorts can feed either Deformetrica
project setup or the [experimental modern workflow](MODERN_WORKFLOW.md);
identical verified requests reuse the same immutable aligned cohort. See the
[format and conversion contract](SURFACE_INPUT_FORMATS.md).

## Per-mesh landmark imports

### Tagged TXT

DiffeoForge can create the canonical cohort CSV from a folder containing one
tagged TXT file per selected mesh. Matching is case-insensitive by filename stem:
`specimen-01.ply` is paired with `specimen-01.txt`. Every mesh in the exact
selected cohort must have one unique match. Each TXT must describe one individual
and declare these sections:

```text
[individuals]
1
[dimensions]
3
[landmarks]
3
[rawpoints]
'#1
1.0 2.0 3.0
4.0 5.0 6.0
7.0 8.0 9.0
```

The declared count must equal the number of finite whitespace-delimited `x y z`
rows, and every file in the cohort must contain the same count. Because this TXT
format does not carry landmark names, row order is the homology contract and the
importer assigns deterministic labels `LM1` through `LMN`. It reports unmatched
TXT files but does not interpret them.

The importer never edits source TXT files, changes coordinate values, infers
units, applies a scale factor, or interprets curve/sliding metadata. The normal
read-only GPA preview remains mandatory after import. Desktop users may use
**Select CSV/TXT/FCSV/JSON...** and choose any one matching TXT, or use **Import
TXT/FCSV/JSON folder...**. Both routes import the complete matched folder and create the
canonical `landmarks.csv` automatically in the project folder; no second CSV
input or save selection is required. If that working CSV already exists, the
desktop asks whether to replace it atomically; declining preserves it byte for
byte. The equivalent CLI command is:

```powershell
diffeoforge landmarks-import-txt C:\study\meshes C:\study\landmarks `
  --mesh-pattern "*.ply" --output C:\study\project\landmarks.csv
```

### 3D Slicer FCSV

Legacy 3D Slicer Markups fiducial files (`.fcsv`) are supported as one file per
mesh. Matching is case-insensitive by exact filename stem, just like tagged TXT.
The importer reads the declared FCSV columns instead of assuming fixed column
positions, accepts both named (`RAS`, `LPS`) and legacy numeric (`0`, `1`)
coordinate-system headers, and handles the two trailing status fields emitted by
Slicer 5.x even though the legacy header does not name them. Only defined control
points are accepted. Every selected file must contain the same ordered point count
and declare the same coordinate system.

Slicer point IDs and labels are not a safe cross-specimen homology key: they may be
duplicated, specimen-prefixed, or regenerated. DiffeoForge therefore preserves row
order as the explicit homology contract and assigns `LM1` through `LMN` in the
canonical CSV. It never converts RAS to LPS (or vice versa), changes units, reflects
points, or interprets curve/sliding semantics. The declared source coordinate
system is reported before the normal read-only mesh/GPA review. Researchers remain
responsible for confirming that the meshes use the same spatial convention.

```powershell
diffeoforge landmarks-import-fcsv C:\study\meshes C:\study\landmarks `
  --mesh-pattern "*.ply" --output C:\study\project\landmarks.csv
```

### 3D Slicer Markups JSON

Slicer Markups JSON (`.mrk.json`, also `.json` with the same content) is supported
natively. Select one representative JSON file or its folder using the desktop
controls above; DiffeoForge imports the matched cohort and selects the generated
project `landmarks.csv` automatically. No external converter is needed.

- `specimen.mrk.json` or `specimen.json` matches `specimen.ply` (or another
  supported surface extension), case-insensitively. Duplicate/ambiguous stems,
  missing matches, or different point counts stop the import before writing.
- Each file must contain exactly one `Fiducial` markup with at least three finite,
  numeric 3D control points. Curves, planes, ROIs, multiple markup lists, and
  undefined/preview points are rejected, not silently flattened or dropped.
- An omitted `positionStatus` uses Slicer's `defined` default, but a valid
  `position` is always required. Hidden/unselected defined points are retained.
- Every file must explicitly declare the same `RAS` or `LPS` coordinate system.
  Units may be a UCUM string or a `[code, coding scheme, meaning]` triple. Unit
  identity is checked across files; missing units are reported as unspecified,
  not guessed. Mixing declared and unspecified units is rejected.
- Source order defines homology and produces `LM1` through `LMN`, as for FCSV.
  Source labels are not sorted or used to infer homology. Coordinates are retained
  as float64 without RAS/LPS conversion, rescaling, reflection, or sliding.

The declared frame and units are shown after import. They do **not** establish
that the meshes use the same convention: confirm this in the required GPA review.
Original files stay unchanged; replacing an existing working CSV requires desktop
confirmation or CLI `--force`, and occurs only after the full cohort validates.
For mixed-format folders, select a representative file to choose which format to
import. Unmatched JSON files are reported but not interpreted.

```powershell
diffeoforge landmarks-import-json C:\study\meshes C:\study\landmarks `
  --mesh-pattern "*.ply" --output C:\study\project\landmarks.csv
```

The coordinate contract follows the official
[Slicer Markups JSON v1.0.3 schema](https://github.com/Slicer/Slicer/blob/main/Modules/Loadable/Markups/Resources/Schema/markups-schema-v1.0.3.json).
Display metadata is ignored and schema URLs inside input files are never fetched.

### Interactive landmark placement

The desktop can create the strict CSV by rotating, panning, and zooming each
mesh, then clicking the visible surface. Each click is resolved by barycentric
interpolation on the frontmost projected source triangle; it is not snapped to
a mesh vertex. The researcher selects the planned label count before the editor
opens; labels begin as `LM1` through `LMN` and remain addable, removable down to
the GPA minimum, and renameable. There is no arbitrary ten-landmark cap. The
editor requires a complete ordered cohort, displays every already placed point,
supports replacement and undo, and never changes the source meshes. After the
last planned point, a visible checkbox controls whether the next mesh loads
automatically or navigation remains manual. Work in progress, including the
label plan and this navigation choice, is written atomically beside the target
CSV. Draft recovery requires the same absolute cohort paths and matching
SHA-256 for every mesh that already has placements. A completed CSV export
removes the draft. Project setup exposes whether landmark-guided alignment is applied,
the shape-only or size-and-shape policy, common working size, reflection policy,
tolerance, and iteration limit.
Before project creation, the guided desktop computes a read-only preview outside
the event loop. It
reports the exact cohort and landmark counts, convergence status and iteration
count, final mean change and total squared residual, per-mesh residual range,
applied scale range, and a content fingerprint. Project creation remains locked
until the researcher approves that exact converged preview. Any path, pattern,
or setting edit invalidates the approval; source contents are hashed again by
the setup service, so an in-place mesh or CSV change is rejected before a
configuration or aligned cohort is published. Step 2 then verifies the
content-addressed aligned meshes and landmark copy against their recorded
hashes before displaying the effective settings.

The input preflight interprets scale in the context of those choices. In a shape-only
analysis, large proportional size differences are expected to be removed from each
complete surface; they are not classified as unit errors merely because raw meshes form
size groups. The fail-closed check is instead within each specimen: its mesh and
landmarks must occupy a compatible coordinate frame so the landmark-derived rigid
orientation can legitimately be applied to that mesh. In a size-and-shape analysis,
large mesh-size groups remain an advisory review item. Geometry alone cannot decide
whether a group represents biology, life stage, acquisition units, or preprocessing
history, and DiffeoForge neither rescales nor rejects it automatically.

Every newly published aligned cohort contains `scaling-sensitivity.csv` and the same
data, interpretation boundary, and hash in `procrustes.json`. The diagnostic compares
all supported scale definitions on the exact cohort and highlights disagreement between
vertex-based and area-weighted size. It deliberately runs no atlas. If conclusions
depend on size treatment, complete shape-only and size-preserving atlas runs must still
be compared.

The visual GPA review is a finite sequence. It reports both the current mesh
number and the number of unique meshes viewed. **Next** stops at the final mesh
and changes to **Last mesh reached**; it never silently wraps to the beginning.
After every mesh has been visited, **Review again from first mesh** provides an
explicit restart while preserving the completed unique-view count. Direct
selection and highest-residual inspection remain available throughout.

For high-resolution cohorts, this review retains a deterministic display proxy
of at most 8,000 source faces per mesh. Exact source hashes, bounds, and face counts
remain visible evidence; the numerical GPA and every downstream atlas computation
continue to use the complete source geometry. Approved preflight metadata are reused
instead of reparsing the cohort for preview, and project preparation transforms and
writes one full-resolution mesh at a time. The display proxy is never published as an
aligned input and is never a silent decimation step. See
[High-resolution mesh intake](HIGH_RESOLUTION_INPUTS.md).

On Windows, alignment staging directories inherit the selected project's access
control rules, including on NAS/SMB shares and mapped drives. They are created
exclusively with unpredictable names beside the final aligned cohort, preserving
same-filesystem publication. DiffeoForge does not modify existing directory ACLs
or broaden share permissions. Other platforms retain private temporary-directory
permissions. An actual project access denial is still reported; this does not
bypass a read-only share. Previously inaccessible `.aligning-*` remnants are not
reused or automatically granted new permissions.

This remains a bounded surface-landmarking system. The code does not provide
landmark uncertainty estimates, missing-landmark handling, semilandmark sliding,
symmetry models, automated homology, or weights.
The current combined template-and-subject cohort and declared mesh-size policy are
explicit preprocessing choices, not automatically appropriate biological decisions.
The numerical preview is a reproducibility and gross-diagnostic gate, not a
registration rendering, uncertainty estimate, or proof that landmarks are
homologous or biologically suitable.
