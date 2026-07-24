# Landmark-based Procrustes alignment

Status: **tested engine-independent preprocessing integrated into Modern and
Deformetrica project setup, with interactive 3D triangle-surface placement and
hash-validated resumable drafts in the desktop**

Tracked by [scientific-change issue #18](https://github.com/heinjenny95/DiffeoForge/issues/18).

## Purpose and order of operations

The implemented workflow is:

1. record the same ordered homologous landmarks for every specimen;
2. compute and preserve one landmark-derived similarity transform per specimen;
3. apply that transform to every vertex of the corresponding complete mesh;
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
- optionally divides by centroid size (enabled by default);
- estimates a least-squares orthogonal rotation with SVD;
- prohibits reflections by default;
- iteratively updates a centered consensus, normalized to unit centroid size
  when scaling is enabled.

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

The shared preprocessing layer defines a strict long-form CSV with
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
removes the draft. Project setup exposes whether GPA is applied,
unit-centroid-size scaling, reflection policy, tolerance, and iteration limit.
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

This remains a bounded surface-landmarking system. The code does not provide
landmark uncertainty estimates, missing-landmark handling, semilandmark sliding,
symmetry models, automated homology, or weights.
The current combined template-and-subject GPA cohort and default
unit-centroid-size scaling are explicit preprocessing choices, not
automatically appropriate biological decisions.
The numerical preview is a reproducibility and gross-diagnostic gate, not a
registration rendering, uncertainty estimate, or proof that landmarks are
homologous or biologically suitable.
