# Landmark-based Procrustes alignment

Status: **tested engine-independent preprocessing integrated into Modern and
Deformetrica project setup, with guided orthographic vertex placement in the
desktop; arbitrary surface-point 3D placement remains future work**

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
and every subject, writes transformed full-mesh copies, and inventories the
complete transformations and convergence evidence. Raw meshes are never
edited. Content-addressed aligned cohorts can feed either Deformetrica project
setup or the [experimental modern workflow](MODERN_WORKFLOW.md); identical
verified requests reuse the same immutable aligned cohort.

The desktop can create the strict CSV by clicking exact mesh vertices in
aspect-preserving XY, XZ, and YZ projections. It requires a complete ordered
cohort, displays every already placed point, and never changes the source
meshes. Project setup exposes whether GPA is applied, unit-centroid-size
scaling, reflection policy, tolerance, and iteration limit. Step 2 verifies
the content-addressed aligned meshes and landmark copy against their recorded
hashes before displaying the effective settings.

This is a bounded first interactive slice, not a full 3D surface-landmarking
system: only represented vertices can be selected, occlusion is handled by
switching orthographic views, and arbitrary triangle-surface points are not yet
available. The code also does not provide landmark uncertainty estimates,
missing-landmark handling, semilandmark sliding, symmetry models, or weights.
The current combined template-and-subject GPA cohort and default
unit-centroid-size scaling are explicit preprocessing choices, not
automatically appropriate biological decisions.
