# Retained public legacy CPU audit

14 September 2026. Only public CC0 synthetic observations; no private input,
checkpoint or runtime configuration is included. These are diagnostic evidence,
not new accepted reference bytes. See the complete
[interpretation and open acceptance boundary](../../docs/REFERENCE_CPU_DIAGNOSTICS.md).

- `ci-amd-34829353422`: downloaded bounded artifact from the passing AMD EPYC
  7763 [run](https://github.com/heinjenny95/DiffeoForge/actions/runs/34829353422),
  source `e9f5639b524cdd59f2fe6aa39d5f05d772264c92`. All ten reference artifacts
  passed byte-identically. Original archive-relative structure is preserved.
- `ci-intel-34831998568`: downloaded bounded artifact from the failing Intel Xeon
  Platinum 8370C [run](https://github.com/heinjenny95/DiffeoForge/actions/runs/34831998568),
  source `0b555d83f587aed8fd4a11d19aa627d3dd06f3fd`. Eight geometry/parameter
  artifacts byte-identical; convergence and residual thresholds fail. Both static
  probe modes are retained; the full atlas used the unchanged default environment.
- Root `probe-default.json` and `probe-compatible.json`: local Ryzen 9 7950X,
  frozen CPU-wheel runtime, default and per-process `MKL_CBWR=COMPATIBLE` probes.
- Root `probe-debug-dispatch.json`: same local runtime with per-process
  `MKL_DEBUG_CPU_TYPE=5`, an artificial diagnostic override, **not native Intel**.
  The original early report predates adding that variable to the receipt allowlist;
  this provenance note supplies the missing launch context without editing evidence.
- Initial local/AMD CI probes used 16/2 Torch threads respectively. The later Intel
  probe explicitly uses 4 after import. Exact counts remain recorded; do not label
  this a CPU-only controlled factorial comparison.

All 15 dot-operand pairs and five static gradients match between the AMD and Intel
probes. Intel AUTO changes five float32 dot results; Intel COMPATIBLE matches the
AMD static values exactly. **A full compatible-mode Intel atlas is still untested.**
All frozen reference thresholds and bytes remain unchanged.

`checksums.json` protects the 13 original evidence files. Tests verify these bytes
and the stated static-probe relationships. Full-atlas geometry equality is reported
by the linked CI comparisons; this bounded archive deliberately does not duplicate
all reconstructed meshes.
