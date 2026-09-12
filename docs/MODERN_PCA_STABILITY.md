# Modern paired PCA stability

Status: **implemented numerical evidence path; no biological-validity or engine-winner claim**

Two independently verified Modern atlas bundles can be compared without
matching principal-component signs or assuming that individually numbered axes
remain identifiable. DiffeoForge first verifies each complete bundle, reloads
its raw momenta table, recomputes the stored PCA, and checks the PCA summary,
scores, loadings, and mean against that recomputation. It then creates a new
immutable two-file evidence artifact bound to both bundle manifests, momenta,
control-point tables, engine versions, subject order, and the declared component
selection rule.

The recomputation comparison uses relative tolerance `1e-12` and absolute
tolerance `1e-13`. The absolute floor covers floating-point SVD differences
near zero across supported NumPy/BLAS patch versions while remaining many
orders of magnitude below the stored biological signal; it is not a tunable
command-line acceptance threshold.

The comparison reports:

- linear CKA for the paired subject scores, invariant to signs, orthogonal
  rotations, and one common isotropic score scaling;
- Spearman correlation of all paired inter-subject score distances; and
- loading-subspace principal angles only when the two control-point CSV files
  have the same SHA-256 identity and the selected component counts agree.

The control-point identity requirement is deliberate. A loading called
`control_point_0010:x` in two separately optimized grids is not automatically
the same anatomical feature. Score-space evidence remains available because
subjects are paired by exact labels, but loading angles are withheld when the
control-point bytes differ.

By default each PCA contributes the minimum number of components reaching 90%
cumulative variance. That may produce different component counts; an explicit
common count can be selected with `--components` when it was justified before
inspection.

```powershell
diffeoforge modern-pca-stability `
  "C:\result-a\atlas-bundle" `
  "C:\result-b\atlas-bundle" `
  --output "C:\comparison\modern-pca-stability-v0.1" `
  --variance-target 0.90

diffeoforge modern-pca-stability-verify `
  "C:\comparison\modern-pca-stability-v0.1"
```

The destination must not already exist. Verification rechecks both current
source bundles and exactly recomputes the comparison. Moving, changing, or
replacing either source invalidates the artifact rather than silently
reinterpreting it.

High score stability means that the two fitted numerical representations retain
similar relationships among these same specimens. It does not show that the
axes have biological meaning, that taxonomic groups are separated correctly,
that registrations are anatomically homologous, or that one engine should be
preferred. Those claims require independent anatomical evidence and a
prospectively declared decision protocol.

## Observed 236-subject Euclidean/Sobolev comparison

On August 27, 2026, the verified Engine 1.5 Euclidean and Engine 1.6 Sobolev
236-subject Trochanter bundles were compared with an explicit 90% cumulative-
variance rule. The Euclidean PCA required 37 components and retained
`0.9016423725` variance; the Sobolev PCA required 39 components and retained
`0.9013074137`. Paired score geometry was highly similar:

- linear CKA: `0.9865289939`;
- inter-subject distance-rank correlation: `0.9893714007`.

Loading-subspace angles were correctly withheld. The Euclidean control-point
CSV has SHA-256 `0cbc86fbe4c9ca658b700288e31e6ab41c960ff553f6cc6e4655fb2fabb02697`,
whereas the Sobolev control-point CSV has SHA-256
`4c13ddcc666c79528a7f38e996c88600cb76a6bdce2203592e79c09bdd9fd205`.
Matching numbered momenta coordinates therefore are not treated as homologous
features.

The immutable evidence directory is
`C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-euclidean-vs-engine16-sobolev-pca-stability-v0.1-236-subject`.
Its manifest SHA-256 is
`285ebb6419424e156b06f391d60110faa39f53f423e7e08b68d35df7e069e97c`.
This retrospective numerical comparison was not a gate in either already
frozen qualification and supplies no pass threshold or biological-validity
claim.
