# Synthetic Deformetrica reference v1

This directory turns the CC0 synthetic cohort into an executable numerical
regression case. It contains selected outputs from two successful CPU runs of
Deformetrica 4.3.0 and a machine-readable manifest that maps them back to the
original run filenames.

## Recorded experiment

- input: one template and five synthetic subjects, each with 162 points and
  320 triangles;
- engine: Deformetrica 4.3.0, Python 3.8.20, PyTorch 1.6.0, PyKeOps 1.4.1,
  NumPy 1.24.4, and SciPy 1.10.1;
- runtime: WSL2 CPU, four threads, KeOps kernels, Float32;
- optimizer: Gradient Ascent with a requested maximum of 100 iterations;
- observed stop: convergence tolerance reached at iteration 22;
- objective: log-likelihood improved from -44.07 to -0.4679;
- residuals: 0.0001268 to 0.0012875, mean 0.0006238;
- outputs: 61 files and 574,096 bytes per complete local run.

Both runs returned zero and produced the same 23-row convergence CSV. All 60
shared output paths were byte-identical. Their timestamped log filenames were
the only inventory-path difference.

The manifest hashes the portable public configuration. For local execution,
only operational fields changed: input and output paths became absolute Windows
paths, and the native launcher became an Ubuntu WSL launcher for the verified
virtual environment. No model, optimizer, precision, seed, kernel, or thread
parameter changed.

## Included artifacts

The fixture retains convergence data, control points, momenta, residuals, the
estimated template, and all five final reconstructions. Intermediate flow
meshes, timestamped logs, and the binary checkpoint are omitted because they
are not needed for the initial regression contract.

`reference-manifest.json` records provenance, environment versions, SHA-256
integrity hashes, run-path mappings, and draft numeric tolerances. Compare a
new completed run with:

```bash
diffeoforge compare-reference runs/my-synthetic-run reference/synthetic-v1
```

Exit code 0 means every selected artifact passed its structural, maximum
absolute difference, and RMS difference thresholds. Exit code 4 means at least
one numeric comparison failed. Exact hashes are reported as additional
same-environment evidence but are not required for a tolerance-based pass.

## Scientific boundary

The current `1e-6` maximum-absolute and `1e-7` RMS thresholds are conservative
engineering regression gates. They have not yet been calibrated across
operating systems, CPU architectures, BLAS implementations, or a pinned
container and are not scientific equivalence criteria. The synthetic surfaces
have no biological meaning.

The selected reference artifacts are dedicated to the public domain under
CC0 1.0. See [LICENSE.md](LICENSE.md).
