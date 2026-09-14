# Public synthetic CPU platform observation, v1

These are the exact compact artifacts downloaded from
[CI run 34825159534](https://github.com/heinjenny95/DiffeoForge/actions/runs/34825159534),
not private biological data or full run directories. Source input is the CC0
`examples/synthetic/meshes` fixture. No additional permissions or releases are
implied by recording this development observation.

- Development head: `727dcd2bfba32302617ffa5162259c98fb86d04e`.
- GitHub pull-request merge checkout actually tested:
  `7b6506bd4c46c94ee648caf931c6bd2d6387ebf1`; its parents were verified as main
  `2d30a0c8b37a5ef855953fc51d6f3c333a9ca28b` and that development head.
- All three observations have identical package/fixture hashes and engine 1.8,
  PyTorch 2.13.0, NumPy 2.5.1 provenance.
- Modern CPU selection: **521 passed on each** Windows x64, Linux x64 and
  Apple-Silicon macOS runner, plus the complete public observation protocol.
- Desktop-only selection, with Torch absent: **197 passed / 14 skipped** on
  Windows; **190 passed / 21 skipped** on Linux, Apple-Silicon and Intel macOS.
  Skips are optional numerical tests and, off Windows, native Windows-only tests;
  numerical execution is covered independently by the Modern matrix.
- All three platform pairs passed the frozen symmetric `atol=1e-10, rtol=1e-8`
  comparison. Maximum absolute differences across scenarios/pairs: template
  `4.72e-16`, reconstructed coordinates `1.34e-15`, control points `6.61e-15`,
  momenta `3.61e-16`, objective components `7.11e-13`, residuals `3.56e-15`.
- Independent local recomparison reproduced the hosted comparison bytes exactly:
  SHA-256 `3f1b5ce140c358971f05e128e5c323f5a287ecbbc0f4ad1e7d6d070b42b64e68`.

The **overall CI run was not green**: the separate full Python suites lacked the
Modern dependency required by a mixed reference/Modern test module. Subsequent
commits correct that environment and isolate Windows mocks that broke Linux
pytest; this earlier platform observation must not be presented as full-suite
success. See `docs/PLATFORM_COMPATIBILITY.md` for the latest follow-up status.

Recompute from the retained exact observations (use a new output path):

```sh
python tools/platform_compatibility.py compare \
  --input reference/platform-compatibility-v1 \
  --output /path/to/new-independent-comparison.json
```

The SHA-256 sidecars are checked before comparison. All original observation
arrays are retained to make the calculation reproducible after CI artifacts
expire. This is small synthetic CPU/offscreen-wheel compatibility evidence only,
not a native installer, real-window UX, Intel-Mac Modern, GPU/MPS, biological,
performance or Deformetrica-replacement qualification.
