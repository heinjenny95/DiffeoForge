# Landmark-based Procrustes alignment

Status: **tested numerical prototype; not yet connected to mesh-run preparation**

Tracked by [scientific-change issue #18](https://github.com/heinjenny95/DiffeoForge/issues/18).

## Purpose and order of operations

The intended future workflow is:

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

## Scientific limitations

The code does not yet provide landmark file formats, specimen/landmark labels,
interactive landmark placement, uncertainty estimates, missing-landmark
handling, semilandmark sliding, symmetry models, weights, GUI review, or
integration into immutable atlas manifests. Those require separate schemas and
validation. A user must be able to inspect raw and aligned meshes side by side
before any atlas run.
