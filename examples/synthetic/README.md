# Synthetic ellipsoid cohort

This directory contains the reproducible, openly licensed miniature surface
dataset used by the DiffeoForge example configuration and automated tests.

The cohort consists of one template and five subjects. Every surface is a
closed triangular mesh with 162 points and 320 faces. The meshes share an
icosphere base topology, then receive different deterministic smooth scaling,
bending, twisting, bulging, and translation transforms. Coordinates are
unitless.

Regenerate the committed files from the repository root:

```bash
python examples/synthetic/generate_dataset.py
python examples/synthetic/generate_dataset.py --check
```

`meshes/dataset-manifest.json` records the construction parameters and SHA-256
digest of every VTK file. No random values, external data, or third-party
geometry libraries are used.

The dataset is intended for installation checks, preflight tests, integration
tests, tutorials, and future numerical regression fixtures. It is deliberately
small and biologically meaningless; it must not be presented as evidence of
scientific validity or performance on empirical anatomy.

The generated dataset is dedicated to the public domain under CC0 1.0. See
[LICENSE.md](LICENSE.md).
