# MARGO human mandibles: dataset intake

This is a preparation record, not a completed DiffeoForge benchmark or a clinical
validation. Originals must remain unchanged until coordinate compatibility and
anatomical scope have been reviewed.

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

This record does not add a Viewbox XML importer, change DiffeoForge parameters,
or authorize repairs, coordinate conversion, mesh simplification or an atlas run.
