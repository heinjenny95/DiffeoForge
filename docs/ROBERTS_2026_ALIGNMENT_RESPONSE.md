# Roberts et al. (2026) alignment and scaling response

Status: **implemented scientific controls and compatibility outputs; biological
cross-dataset validation remains prospective**

## Why this matters

Roberts et al. show that alignment and scaling are not neutral housekeeping steps in
landmark-free morphometrics. Alternative preprocessing can change variance allocation,
principal-axis order, group dispersion, and the biological interpretation of an atlas
morphospace. A technically converged atlas therefore does not settle whether a shape-only
or size-and-shape analysis answered the intended question.

The paper's PAMS route uses homologous landmarks to orient meshes without scaling them
from landmark centroid size, then normalizes each complete mesh by its own vertex
centroid size. Its published postprocessing applies RBF KernelPCA to flattened
Deformetrica momenta with `gamma = 0.00000025`.

Sources:

- [Paper DOI](https://doi.org/10.1111/joa.70227)
- [Public analysis repository](https://github.com/LucyEmmaRoberts/landmark-free)
- [Published mesh-alignment code](https://github.com/LucyEmmaRoberts/landmark-free/blob/main/Mesh_alignment.R)
- [Published Deformetrica postprocessing code](https://github.com/LucyEmmaRoberts/landmark-free/blob/main/Processing_Deformetrica_outputs.py)

## DiffeoForge implementation

DiffeoForge now makes the two decisions explicit and independent:

1. Homologous landmarks estimate translation and orientation only.
2. A named complete-surface policy determines whether and how size is removed.

The new desktop default is **Shape only — surface scale, resolution-independent**. It
uses exact first and second moments of every triangle to calculate an area-weighted RMS
surface radius. Subdividing an unchanged triangular surface leaves this measure
unchanged apart from floating-point roundoff.

For exact methods comparison, **Shape only — published PAMS vertex centroid size** uses
the complete vertex matrix exactly as the public PAMS code does. This measure can change
when the same surface is tessellated differently; DiffeoForge reports that limitation
and warns when cohort vertex counts differ materially. The desktop preset selects the
published common working size of 1000; changing it is recorded and requires new pilot
calibration of absolute atlas parameters.

**Size + shape — preserve specimen size** provides a form-space route. Two legacy modes
preserve reproducibility for older configurations: landmark-centroid-size similarity
scaling and the previous rigid-GPA behavior.

Every aligned cohort records raw landmark centroid size, vertex centroid size,
area-weighted surface radius, surface area, final scale factor, post-transform measures,
and a hash-bound `scaling-sensitivity.csv`. The sensitivity diagnostic evaluates all
policies without rerunning an atlas and states explicitly that it cannot establish atlas
or morphospace robustness.

The reference-engine shape-space comparison additionally exports the Roberts fixed-gamma
RBF KernelPCA preset on flattened Cartesian momenta. DiffeoForge retains deformation-
kernel metric tangent PCA as its model-aligned default because it preserves the fitted
LDDMM tangent metric and supports reconstruction to shootable momenta. The Roberts preset
is a named compatibility analysis, not an automatic replacement or superiority claim.

## Required validation before biological claims

For a representative public dataset with landmarks, complete atlases should be run from
at least the area-weighted shape-only, exact PAMS, and size-preserving preparations while
holding atlas parameters and subject inclusion fixed after scale-appropriate calibration.
The comparison should report template distance, registration residuals, outlier overlap,
PCA subspace angles, score-distance agreement, and whether qualitative biological
conclusions change. If mesh resolution varies, a controlled equal-tessellation comparison
should isolate biological scaling from vertex-sampling effects.

No mode should be declared universally correct. Shape-only normalization answers a
different biological question from form analysis, and exact paper reproduction may
justify a resolution-sensitive compatibility method that is not the best general default.
