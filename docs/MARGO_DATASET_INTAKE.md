# MARGO human mandibles: dataset intake

This is a preparation record, not a completed DiffeoForge benchmark or a clinical
validation. Originals remain unchanged; derived coordinate exports must be kept
separate and anatomical scope still requires review.

## Pinned public source

- Dataset: Halazonetis, *Maxillofacial bone dataset for the MARGO project*,
  [Zenodo record 10170185, version 0.5.0](https://doi.org/10.5281/zenodo.10170185),
  licensed CC BY 4.0. Cite the version-specific record, not only its concept DOI.
- Study: *Shape variation and sex differences of the adult human mandible
  evaluated by geometric morphometrics*,
  [Scientific Reports (2024)](https://doi.org/10.1038/s41598-024-57617-7).
- Required source files: `M_mandible.zip`, `Margo100_GM_slide.xml`,
  `MargoTemplate.zip`, and `Info.xlsx`. CT thumbnails are not needed for this
  mesh/landmark intake.

Download against the pinned record metadata. Verify the published MD5 and byte
count of each file, record SHA-256 hashes, and extract into separate original
mesh and template directories with ZIP path-traversal and collision checks.
Keep data, patient-level metadata, and local paths out of the source repository.

## Cohort and landmark contract

The archive contains 115 subject PLY meshes, but the landmark XML contains 100
unique subject IDs. Pair by the XML ID and the corresponding `Mxxx_mandible.ply`
filename, retaining a manifest of the 15 meshes outside the landmark cohort.
File-name agreement alone does not prove spatial registration.

The XML stores 521 point records per subject. In `MargoMandible.vbrx`, the
`All points shape` definition selects 519 points and omits template indices 6
and 7 (`Gnathion R` and `Gnathion L`). Template indices are one-based; XML point
IDs are zero-based. Preserve original IDs and use this explicit mapping, not
the first 519 records. The supplied `Full` sliding group has 9 mode-0 points,
84 mode-1 points and 426 mode-2 points, corresponding to fixed, curve and
surface landmarks in the study design.

Do not describe all 519 coordinates as independently placed fixed landmarks.
The delivered coordinates have already undergone the authors' landmarking and
sliding workflow. A later independent-comparison protocol must state whether
these points also guide DiffeoForge's initial alignment.

## Before any atlas run

1. Validate all point IDs, counts, finite coordinates and mesh/metadata matches.
   Preserve original metadata values and document any derived normalization.
2. Resolve coordinates and units before conversion or GPA. The XML and archive
   PLY coordinates are not directly interchangeable: their observed positions
   and scales differ, and the XML's linked mesh paths are not supplied in the
   mesh archive. Identity matrices in the XML do not establish compatibility
   with differently named archive meshes. Do not assume that a global scale
   factor alone fixes the mismatch. Establish a documented transform or obtain
   matching mesh-coordinate landmark exports, then verify overlays and distances.
3. Run the existing structural mesh-quality checks without processing the
   inputs. Save per-mesh metrics and the exact gate settings. Open surfaces and
   multiple components require review; do not silently fill or discard them.
   These checks do not establish freedom from self-intersections or anatomical
   validity.
4. Review dental regions explicitly. The paper reports unreliable tooth
   surfaces from restoration/prosthesis artifacts, and includes tooth loss and
   alveolar resorption. Full-surface registration can weight regions differently
   from the published landmark analysis. Agree on the anatomical scope before
   interpreting any comparison; do not silently crop teeth or exclude specimens.
5. Retain original resolution initially. Choose any working-copy resolution by
   anatomical detail and a documented sensitivity assessment, not a universal
   face-count target. Estimate the actual workload before starting the pilot.

## Coordinate recovery protocol (2026-09-11)

At the user's request, coordinate reconciliation is performed on separate
working copies. The source PLY meshes retain their bytes, geometry and resolution;
only landmark coordinates are converted into the corresponding mesh's native
frame. This is **within-subject frame reconciliation**, not between-subject GPA,
an atlas fit or a biological validation.

The source XML does not supply a verified transform to these archive PLY files.
For this pinned dataset, estimate a proper rigid transform after a single common
XML scale factor of 0.1. For row vectors, the recorded convention is
`p_mesh = (0.1 * p_xml) @ R + t`, with `det(R) = +1`. Also save the equivalent
column-vector homogeneous matrix, source hashes and inverse checks. This is an
empirical recovery, **not an author-exported transform or a generic Viewbox unit
rule**. Native PLY units are interpreted as millimetres, not independently
calibrated physical measurements.

- Fit only 213 alternating surface semilandmarks in the source sliding-group
  order. Reserve the other 213 surface points, all 9 fixed landmarks and all 84
  curve landmarks for geometric checks. These are non-fit points on the same
  specimens, not an independent biological holdout cohort.
- Use 24 proper PCA-frame initializations with nearest-vertex rigid ICP, then
  refine the best and a distinct second coarse solution against exact nearest
  triangle distances on the full mesh. Select using fitting points only.
- Diagnose an additional free uniform scale, but never apply it to the exports.
  Retaining the one common 0.1 factor preserves between-subject size variation.
- Screen non-fit surface RMS <= 0.1, fixed-point RMS <= 0.25, fixed-point maximum
  <= 1.0 and all-519 p95 <= 1.0 in native mesh units; also require restart maximum
  displacement <= 0.05 and free-scale deviation <= 0.001. Require converged
  optimizers, proper orthogonal rotations, inverse consistency and unchanged
  scaled pairwise distances. These are engineering screens, not clinical limits.
- Preserve residual curve-point offsets. Do not snap individual points to the
  surface, re-slide them, reflect specimens, apply nonrigid/affine fitting,
  smooth/repair meshes or remove teeth to improve the recovery metrics.
- If the second distinct coarse solution reaches a competing local minimum,
  retain that failed screen and inspect additional original PCA initializations.
  Release only when at least three starts reproduce the unchanged primary
  transform within the existing displacement threshold, and all distance,
  scale and preservation screens pass. Record this resolution separately; do
  not erase the initial warning or increase distance tolerances.
- Inspect overlays of representative cases and the worst numerical cases before
  handing off. Surface proximity alone does not establish anatomical homology.

Export the canonical `mesh_file,landmark,x,y,z` CSV for the exact 100-mesh cohort:
519 points in the template's shape order, plus a separately named 9-fixed-point
alternative. Labels retain XML IDs and a sidecar maps labels, template indices,
names and modes. Keep all 521 transformed source points in an **audit-only**
file; the two omitted points must not silently enter the published-shape set.
Choose the later alignment strategy explicitly. Using source landmarks for
prealignment limits the independence of a subsequent landmark-method comparison.

Keep per-subject coordinates, transforms, meshes and review images local. The
public repository contains this protocol and aggregate verification only. This
preparation does not add an automatic XML importer, change application behavior,
select atlas parameters or start a pilot/atlas.

### Verification of the prepared cohort

All 100 paired original-resolution meshes were copied byte-for-byte (26,164,848
faces). All 122 downloaded/extracted original files were rehashed successfully.
The canonical DiffeoForge landmark reader accepted both `(100, 519, 3)` and
`(100, 9, 3)` exports; the fixed set is an exact subset, with rank 3 in all cases.
CSV roundtrip error was zero. The scaled pairwise-distance maximum error was
`1.57e-13` mesh units; inverse XML error was below `1.31e-12` source units.

Across the 21,300 non-fit surface points, pooled RMS/p95 were
**0.008323 / 0.017101** native mesh units. Across the 900 fixed points,
RMS/maximum were **0.018890 / 0.164445**. Curve offsets were retained:
p95/maximum **0.396971 / 1.771540**. These are point-to-triangle proximity
measurements, not landmark annotation accuracy or clinical validation.
The diagnostic additional scale ranged from 0.999960 to 1.000122 and was not
applied. Two competing-start warnings were resolved with three agreeing original
initializations each; all original warning records and primary transforms remain.

Six cases were reviewed in three full-resolution overlay projections each,
including both resolved warnings and the worst numerical cases. No gross frame
mismatch was visible; this is not a 100-subject anatomical sign-off. The existing
landmark/mesh I/O suite passed 28 tests; four local preparation tests covered
transform/inverse convention, reflection rejection, initializations and CSV order.
No application code, installer, atlas parameters or existing runs were changed.
