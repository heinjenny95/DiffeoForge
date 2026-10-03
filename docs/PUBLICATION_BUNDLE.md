# Verified publication bundle

Status: **implemented immutable export; no automatic raster or video claims**

`publication-export` operates only on an already completed and independently
verified Modern or Deformetrica-reference atlas. It does not run optimization,
refit PCA, modify a source result, or edit a presentation graphic.

The default destination is an absent sibling named `<run>-publication`. The
export contains:

- a newly composed and verified scientific atlas report;
- every verified source SVG exposed by result review;
- open CSV, JSON, and text tables/evidence exposed by result review;
- the estimated template and available mean/positive/negative PCA endpoint VTKs;
- a figure-caption CSV, a script-free HTML index, and a plain-text boundary note;
- a recursive exact-file inventory with byte counts and SHA-256 hashes.

Subject reconstructions remain in the verified source run by default because a
large cohort can make a handoff unnecessarily large. The CLI flag
`--include-reconstructions` explicitly includes their verified VTK copies.

```powershell
diffeoforge publication-export C:\study\runs\atlas-v50
diffeoforge publication-verify C:\study\runs\atlas-v50-publication
```

Optional sensitivity, template-robustness, fixed-template holdout, PCA-stability,
and researcher-decision evidence can be supplied with the same paths accepted by
`scientific-report`. The nested report binds those sources by hash and marks
missing evidence as unassessed.

## Why SVG remains canonical

The verified plots are copied byte-for-byte as open, resolution-independent SVG.
DiffeoForge does not silently choose journal DPI, physical dimensions, font
substitution, colour profile, or a background when rasterizing. Those are
publication decisions, so automatic transparent PNG export remains deliberately
unclaimed until an explicit, reproducible raster profile is implemented.

Likewise, positive and negative PCA endpoint meshes do not constitute a sampled
diffeomorphic path. DiffeoForge therefore does not interpolate them into a video
and label that result a deformation animation. A future video export must consume
an inventoried time-resolved Shooting/flow artifact.

## Verification

`publication-verify` rejects symbolic paths, missing or additional files, changed
bytes, an altered manifest/sidecar, a changed nested scientific report, or changed
source evidence. It then reverifies the source atlas and its analysis bundle. A
successful check is reproducibility evidence, not biological validation.
