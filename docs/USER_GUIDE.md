# DiffeoForge desktop guide

This guide describes the source interface. Check [source status](DEVELOPMENT_CONTINUITY.md)
and your installed application version separately.

## Prepare and align

Choose a mesh folder, initial template, project folder and known units. Preserve
received originals. Mesh validation checks structure, not anatomical completeness.

**Initial template:** choose a complete, clean, broadly representative surface.
Avoid an extreme specialization or damaged specimen merely because it has more
vertices. **Analyze meshes & suggest template** compares geometric descriptors
and quality warnings in the background without fitting. Preview the suggestion
and alternatives, then explicitly choose **Use selected template**. Before
applying a choice, the ranking's complete source cohort is checked in the
background without parsing the meshes again. You can cancel this check. A new
analysis retires the previous suggestion immediately, and changed files require
a fresh recommendation. Changing the file pattern or project retires the old
recommendation too. Unreadable inputs remain visible as unresolved warnings.
This is starting guidance, not anatomical approval or a promised best final atlas.

**Landmarks:** use the same identifiable anatomical locations in the same order
on every mesh, including the template. Use at least three well-spread points
which do not lie on one line. Suitable junctions, attachment boundaries or tips
depend on the organ and question. Do not guess missing features or substitute a
nearby projection. The editor's **Where should I place landmarks?** panel provides
more guidance. These points guide alignment, not atlas attachment constraints.

**Alignment:** the description below the selector follows the current choice:

| Choice | Effect |
| --- | --- |
| Shape only, area-weighted surface scale | Removes position, orientation and surface size; scale is robust to triangle subdivision. |
| Published PAMS, vertex centroid size | Uses whole-surface vertex centroid size and its published working-size preset; vertex density can affect scale. |
| Size + shape | Removes position and orientation while retaining size differences. |
| Legacy, landmark centroid size | Landmark configuration determines scale as well as orientation. |

Enable reflections only when mirrored forms are biologically interchangeable.
Inspect the aligned cohort before approval. Changed settings invalidate the
previous preview. See [alignment contracts](PROCRUSTES_ALIGNMENT.md).

## Test the pilot

The practical goal is captured important projections and the right overall shape;
small surface differences can remain. Newly prepared guarded regional fits offer
an [intermediate review after ten active minutes](PILOT_INTERMEDIATE_REVIEW.md).
Allow another ten minutes in the same optimizer, or finish fitting and let the
normal export/QC complete. This does not silently change existing prepared studies.

Compare methods and contrasting forms before using settings for the cohort.
Matching settled previews suffice for approving, rejecting and comparing pilot
fits; full detail is optional. Mark problem areas and explain the error, while
retaining useful earlier fits. A numerical stop and a suitable anatomical fit
are different decisions. Source-interface changes do not require restarting an
existing owner test.

Saved problem-area marks remain active until explicitly cleared. To request an
unmarked follow-up, use **Clear marked areas** in the fit inspector and save the
feedback before preparing the next trial. An already prepared trial keeps its
recorded inputs and objective.

## Understand shape-space methods

Short descriptions appear beside method choices and saved-method views. Method
IDs, presets and numerical calculations are unchanged.

| Method | Meaning |
| --- | --- |
| LDDMM-metric tangent PCA | Fitted momenta in the deformation metric; the default tangent approximation to PGA. Axis shapes use shooting. |
| Tangent-distance PCoA | Coordinates from tangent distances; a cross-check of the same tangent geometry. |
| Cartesian momenta PCA | Raw momentum coordinates without the LDDMM metric; a legacy comparison. |
| Published Cartesian RBF preset | Fixed-gamma nonlinear compatibility analysis, distinct from tangent PCA. |
| Generic RBF KernelPCA | Nonlinear tangent-distance view whose scale depends on gamma. |
| Isomap | Neighborhood-path structure; exploratory and neighborhood dependent. |
| Diffusion map | Neighborhood connectivity; axes are not PCA explained-variance percentages. |

These views do not establish groups, causation or good registration. Read the
[complete method contract](REFERENCE_PCA.md).

## Explore and export

Visualization separates five views of the saved PCA: **2D scores**, **PC shapes**
(mean and ±2 SD), **Maps** (endpoint movement), **Movies** (PC deformation in six
views), and **3D scores** (rotatable PC1–PC3). These tabs are display choices,
not different PCA methods. Context help explains each tab. **Mesh size** applies
to 2D glyphs. With only one saved component, **PC1 scores** shows a single score
line without inventing PC2. Unavailable PC pairs and missing media tabs are
disabled with explanations. A 3D export waits for its display geometry to load.
The current-view export names its medium; **Export all media (ZIP)**
saves the gallery. Exporting does not refit an atlas or recompute PCA.

**Export data for R / geomorph** identifies each data source: a reviewed result
enables saved PCA export; selected complete landmark inputs enable a separate
geomorph handoff. See [R export contents and interpretation](R_EXPORT.md).

For help, use the [issue chooser](https://github.com/heinjenny95/DiffeoForge/issues/new/choose)
with a version and synthetic or licensed public reproduction. Keep private
specimen data and checkpoints out of public reports.
