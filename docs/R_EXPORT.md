# R and geomorph data handoffs

Use **Export data for R / geomorph** in Results or Visualization, or **Export
landmarks for R / geomorph** beside the landmark inputs. This exports data;
it does not invoke R, install packages, fit an atlas, change input coordinates
or approve scientific results.

Choose a data type and a new ZIP filename. Work runs outside the GUI thread.
The dialog lists which sources are selected and explains missing prerequisites.
geomorph selection requires an existing CSV, a declared template and at least
two subjects; complete table validation still occurs during export. The action
is labelled **Save data for R (ZIP)**: this is a data archive, not an installable
R package. Supplied coordinate units are shown without conversion.
ZIP entries are byte-verified before exclusive publication. Existing destinations
are preserved; changed source bindings stop publication. The manifest records
source hashes, specimen order, representation and output checksums.

## Saved atlas PCA for base R

A reviewed result exports its actual saved method, without substituting a fresh
Cartesian PCA for the LDDMM-metric PCA.

| File | Contents |
| --- | --- |
| `scores.csv`, `specimens.csv` | Saved scores, exact labels and row order |
| `variance.csv` | Component variances and explained-variance ratios |
| `pca-summary.json` | Feature space, rank, spectrum, labels and sign convention |
| `loadings.csv` | Saved loadings when the reviewed result exposes them |
| `load_pca.R` | Base R loader and optional interactive plot |
| `README.txt`, `export-manifest.json` | Usage and provenance |

Extract the archive, set R's working directory to it, then run:

```r
source("load_pca.R", encoding = "UTF-8")
head(scores)
head(variance)
```

`score_matrix` contains the saved scores. Join metadata by `subject_label`, not
assumed alphabetical order. The loader preserves leading zeros and literal `NA`
labels as text. No R package is required. Signs remain conventional; unresolved
source QC remains unresolved.

## Supplied landmarks for geomorph

This requires a complete canonical landmark CSV and selected input cohort. Every
mesh needs the same unique labels in the same order, finite coordinates and at
least three distinct non-collinear points. The separately declared template is
excluded; no other specimen is silently dropped.

`coordinates.csv`, `landmarks.csv` and `specimens.csv` define a
**landmark × xyz × specimen** array. Coordinates remain in the supplied CSV's
frame and units; DiffeoForge's alignment transform is not applied. Names are
stored as data, never interpolated into executable R code.

```r
source("load_landmarks.R", encoding = "UTF-8")
dim(coords)
dimnames(coords)
```

Loading uses only base R. To explicitly run the separate GPA/PCA example with an
already installed geomorph package:

```r
source("analyze_geomorph.R", encoding = "UTF-8")
```

The example uses `gpagen` with fixed landmarks, no assumed semilandmark sliding,
and `gm.prcomp`. GPA removes landmark centroid size. That differs from
DiffeoForge's whole-surface size policies, so this landmark PCA is not the saved
LDDMM atlas PCA. Raw momenta and independently numbered mesh vertices are not
exported as homologous landmarks. Biological homology remains human review.

The array convention follows the [geomorph data tutorial](https://geomorphr.github.io/Tutorials/1.2-ReadingData.html).
See [alignment policies](PROCRUSTES_ALIGNMENT.md) and [PCA methods](REFERENCE_PCA.md).
