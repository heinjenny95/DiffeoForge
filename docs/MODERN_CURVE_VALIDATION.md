# Modern manual-curve validation

Status: **implemented retrospective pilot path; no final biological-validity or
engine-winner claim**

This path compares two already completed Modern atlas bundles against manually
traced surface curves. It does not run or continue an atlas optimizer.

The input mapping is explicit rather than inferred from filenames. Its exact
columns are:

```text
curve_csv,legacy_aligned_mesh,legacy_raw_mesh,legacy_anchor_file,current_subject_label,status,note
```

Every candidate is marked `include` or `exclude`. Included rows require all
legacy sources plus an exact Modern subject label. Excluded rows require a
reason. Duplicate curves or included subjects are rejected.

For each included subject DiffeoForge:

1. recovers the legacy aligned-to-raw similarity from equal-topology mesh
   vertices;
2. transfers the legacy raw coordinates to the current raw coordinates through
   the three independently stored GPA anchors;
3. audits 512 deterministic legacy surface vertices exactly against every
   triangle of the current mesh and separately audits the complete manual
   curve;
4. applies the exact current transform recorded in `procrustes.json`;
5. resamples the curve to 64 normalized-arclength positions by default;
6. projects every position to the subject reconstruction and stores its exact
   triangle and barycentric coordinates; and
7. evaluates the same triangle and barycentric coordinates on the estimated
   template.

The primary correspondence metric is normalized leave-one-subject-out curve
RMS in template space. Projection residual, coordinate-transfer residual, and
endpoint-direction consistency remain separate diagnostics. This distinction
is essential: proximity of a curve to a reconstruction measures fit, whereas
agreement of pulled-back curves across subjects is the correspondence question.

```powershell
diffeoforge modern-curve-validation `
  "C:\engine-15\atlas-bundle" `
  "C:\engine-16\atlas-bundle" `
  --mapping "C:\validation\mapping.csv" `
  --curve-directory "C:\manual-curves" `
  --preprocessing "C:\cohort\preprocessing\aligned-id" `
  --output "C:\validation\modern-curve-validation-v0.1" `
  --samples 64

diffeoforge modern-curve-validation-verify `
  "C:\validation\modern-curve-validation-v0.1"
```

The destination must not exist. The immutable two-file artifact binds both
complete Modern bundles, the mapping, all 64 curve-inventory files, every
included legacy source, the current landmark and Procrustes files, and the
current raw meshes by SHA-256. Verification reloads those sources and exactly
recomputes the evidence.

## Observed 16-subject Trochanter pilot

On August 27, 2026, the verified Engine 1.5 Euclidean and Engine 1.6 Sobolev
236-subject bundles were compared against the overlapping manual winding
curves. Of 64 curves, 19 were mapped candidates and 16 were included. Three
were excluded before engine comparison:

- the annotated `Mononychus punctumalbum` mesh was not the Modern rescan;
- the generic `Sitona` curve could not be equated with specimen 313
  `Sitona hispidulus`; and
- specimen 302 failed whole-surface transfer under both proper and reflected
  three-anchor mappings.

Median normalized leave-one-out curve RMS was `0.0726832548` for Engine 1.5
and `0.0691532333` for Engine 1.6. Engine 1.6 was lower for 11 of 16 subjects;
the median paired difference (comparison minus reference) was only
`-0.0016069480`. Pairwise subject-curve distance ranks remained highly similar
(`0.9942426557`).

This small difference is not a winner claim. Median subject projection p95 was
about `0.02249` versus `0.02153`, while legacy transfer residuals were commonly
one to three percent of the current mesh diagonal. Endpoint direction was also
not fully consistent: approximately 27% of pairwise endpoint-direction cosines
were negative in each template. Prospective endpoint semantics, a larger
independent landmark cohort, and a predeclared decision threshold are required
before using this result as biological validation.

The immutable evidence directory is
`C:\Users\js7541\Desktop\DiffeoForge Modern Engine 5k Scaling 2026-08-23\engine15-euclidean-vs-engine16-sobolev-manual-curve-validation-v0.1-16-subject`.
Its manifest SHA-256 is
`eefe2ca1460770cd4632f13f190a02b207d41de9c1fc2400699287aaff8150e9`.
