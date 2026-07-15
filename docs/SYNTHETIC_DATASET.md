# Open synthetic validation dataset

## Purpose

DiffeoForge includes a miniature surface cohort so that a fresh checkout can
exercise the public workflow without unpublished specimen data. It closes the
gap between schema-only tests and the private anatomical reference experiment.

The committed dataset supports four distinct checks:

1. real VTK geometry preflight;
2. deterministic template and subject discovery;
3. immutable run preparation, input hashing, and XML generation;
4. future Deformetrica reference outputs and numerical regression tests.

## Construction

`examples/synthetic/generate_dataset.py` creates a subdivision-level-two unit
icosphere with 162 points and 320 triangles. It applies six explicitly recorded
smooth transformations to create one template and five subjects. The script
uses only the Python standard library, contains no random sampling, writes
stable LF-terminated ASCII VTK PolyData, and records every parameter and file
digest in `dataset-manifest.json`.

The committed bytes can be audited at any time:

```bash
python examples/synthetic/generate_dataset.py --check
diffeoforge validate examples/minimal-atlas.yaml
```

## Licensing and scientific boundary

The generated meshes and dataset manifest are released under CC0 1.0. The
generator itself remains covered by the repository's MIT license.

This cohort has no biological interpretation. Shared topology and its small
size make it useful for software and numerical regression, but unsuitable for
claims about anatomical variability, scientific accuracy, or real-world
scaling. Those questions require separately governed validation datasets and a
predeclared evaluation protocol.

The first Deformetrica 4.3.0 outputs, repeatability evidence, and versioned
numeric comparison thresholds are documented in the
[synthetic reference suite](../reference/synthetic-v1/README.md).
