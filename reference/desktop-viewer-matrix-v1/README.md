# Synthetic desktop viewer size matrix

Observed on 15 September 2026 on the Windows development workstation. This is an
engineering check, not biological validation or a claim that every viewer path
is fast. No atlas or Validation Lab run, alignment publication, QC approval,
landmark draft or private-data upload was performed.

## Scope and reproducibility

`tools/benchmark_viewer_matrix.py` generates three closed ellipsoids with local
shape perturbations and three corresponding landmarks at each of 10k, 100k and
200k triangles per mesh. It runs each size/family in a fresh offscreen Python/Qt
process, with a native event loop and a 900 × 650 viewport:

- `landmark-result-pc`: production `InteractiveMeshCanvas3D`, shared by landmark
  and atlas/PC-surface viewing; two source meshes loaded, one displayed at a time.
- `calibration-registration-qc`: production `CalibrationComparisonCanvas3D`,
  displaying a pair. These are synthetic shape variants, **not atlas fits**.
- `gpa`: real landmark-alignment preview and `GpaAlignmentCanvas3D`, with all
  three 200k sources loaded for the largest condition.

The pair paths use `PreviewMeshLoader`. The complete result-bundle opening and
verification flow is **not** benchmarked, nor are PCA analysis or SVG plots.
Existing result/QC regression tests are separate evidence for those rules.

`plan.json` binds the exact script, eight viewer modules and fixture bytes by
SHA-256 and records Python/platform, viewport, samples and cycles. The observations
were made from development HEAD `94630f8` plus the GPA legend change in this
commit; script/module hashes describe the measured working tree. Recorded paths
are relative, Windows-style fixture paths. No private meshes or installer files
are included here. Synthetic mesh files can be regenerated outside the repository:

```powershell
.venv/Scripts/python.exe tools/benchmark_viewer_matrix.py --output C:/temp/df-viewer-new-matrix
```

Use a new output directory. `--prepare-only` generates and hashes fixtures;
`--run-existing` observes that plan, refusing script/module drift. Existing
observations and PNGs are not overwritten. Original input hashes are checked
before and after each observation. Execution requires the desktop development
dependencies, including PySide6, NumPy and psutil.

## Observations

Times below are single observations rounded to two decimals. Cold load includes
source parsing and display preparation (and GPA for that family). First frame is
the subsequent model installation plus completed display frame, not total startup.

| Faces per mesh | Canvas family | Cold load (s) | First frame (s) | Sampled peak RSS (MiB) |
| ---: | --- | ---: | ---: | ---: |
| 10,000 | Single surface / landmark / PC | 0.21 | 0.09 | 93.1 |
| 10,000 | Calibration / registration QC | 0.21 | 0.13 | 94.2 |
| 10,000 | GPA | 0.53 | 0.12 | 96.5 |
| 100,000 | Single surface / landmark / PC | 1.75 | 0.09 | 168.3 |
| 100,000 | Calibration / registration QC | 1.78 | 0.16 | 173.0 |
| 100,000 | GPA | 4.29 | 0.11 | 165.0 |
| 200,000 | Single surface / landmark / PC | 3.59 | 0.12 | 271.9 |
| 200,000 | Calibration / registration QC | 3.52 | 0.22 | 267.7 |
| 200,000 | GPA | 9.03 | 0.11 | 262.0 |

At 200k faces, the five sampled navigation frames took approximately 30–80 ms
across families. Switching already loaded specimens took 0.11 s (single), 0.26 s
(QC pair) and 0.08 s (GPA). Explicit original detail took 1.79 s for a single
surface and 2.38 s for the QC pair. The largest GUI-timer gap was 0.49 s during
full-detail QC: short stalls remain. Raw phase observations are retained in each
size subdirectory; no frame-rate or universal upper-bound guarantee is inferred.

At 200k, display proxies contained 5,224 / 5,069 faces for the pair and 4,869 for
the third GPA mesh. Every condition passed source preservation, three reopen
cycles and destruction during an outstanding render followed by worker drain.
For the two original-detail-capable families, default proxies could not satisfy
the original-detail readiness gate; original detail became ready only after its
frame completed. Hiding the original QC layer disabled readiness; returning to
proxy disabled it again. GPA has no original-detail approval gate.

RSS is sampled every 20 ms: it is a sampled process peak, not exact peak memory
or GPU usage. Post-close values still include loaded models/caches; these short
runs do not prove absence of leaks or scalability to a full large cohort.

## Visual and installed-app checks

The three retained 200k screenshots were inspected: surfaces and overlays are
visible, text is readable, reduced displays are labelled, and source GPA's legend
matches its visible layers. The QC screenshot's reconstruction wording belongs
to the production canvas; its synthetic shapes are not scientific reconstructions.

Separately, the installed `063143a` Windows app loaded the same deterministic
200k fixture geometry: template proxy, rotation, next subject, explicit original
detail, close and reopen all displayed correctly. Reopening restored the template
proxy with original detail off, zero points placed and no saved draft. This was
the landmark editor only; installed large GPA/QC/PCA workflows remain untested.
The installed executable was not rebuilt or changed and still has the old GPA
legend. See `docs/DESKTOP_RENDER_LIFETIME.md` for installed-build provenance.

Final focused regression run: **69 passed**, covering GPA, frame rendering,
display proxies, landmark editing, registration release, calibration dialogs and
the benchmark fixture; Ruff passed. The GPA legend test covers all eight layer
combinations. This matrix does not establish preservation of anatomical defects,
other hardware/platform performance, or resolution of the historical Intel-Mac
native crash. Next: full installed QC/result-bundle checks on a completed cohort,
then package the source correction in the next explicitly requested build.

Development notes: an initial two-mesh fixture was correctly rejected by GPA's
two-target minimum; it was replaced with three meshes. An intermediate successful
matrix lacked readable offscreen fonts. The retained final matrix uses an explicit
Windows Arial font and complete script/module hash checks, not mixed observations
from those earlier attempts.
