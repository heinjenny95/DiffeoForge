# Prospective public full-atlas CPU pair v1

Frozen before observation, 14 September 2026. This is the next diagnostic for
the [retained scalar-reference discrepancy](REFERENCE_CPU_DIAGNOSTICS.md), not a
new engine, installer or product default.

- Use only the six hash-checked CC0 synthetic surfaces, the exact public container
  configuration and the unchanged `synthetic-v1` reference manifest/artifact hashes.
  Float32, four configured threads, one process, fixed seed; no parameter changes.
- Build the existing frozen image unchanged. On each actual Linux x86_64 host,
  run complete atlases in order AUTO-1, COMPATIBLE-1, COMPATIBLE-2, AUTO-2, each
  in a fresh network-disabled, read-only container with its own temporary KeOps
  cache. Only `MKL_CBWR` and a unique cleanup name are added to the generated
  launcher command. All XML and staged input bytes remain protected.
- Compare all ten artifacts using the existing maximum `1e-6` / RMS `1e-7`
  thresholds; report byte identity separately. Require byte-identical repeated
  outputs within each mode. Failures remain evidence, never new reference values.
- Run AUTO/COMPATIBLE static operand probes on the same host at four Torch threads
  after all atlas observations. Retain actual CPU model/vendor, image ID, source
  commit, command, runtime settings, worker hash and all comparison statistics.
- Initial collection: one Ubuntu 22.04 and one Ubuntu 24.04 hosted job. Runner
  labels do not guarantee CPU vendor. Require observed native Intel **and** AMD
  evidence for the requested comparison. If one is missing, retain the capture
  and make at most one additional two-job collection; report any missing coverage.
- Retain exactly the selected numeric/geometry artifacts, model/data/optimization
  XML, logs, static probes and checksums. Independently rederive each comparison
  after downloading. Never upload private data or pickle checkpoints.

`tools/observe_reference_cpu_pair.py` is an isolated diagnostic harness. It uses
normal preparation and the unchanged generated Docker/Deformetrica CLI command,
but does not forge normal app lifecycle completion or publish these as app runs.
Its explicit execution receipt records the added mode. The installed software,
production launcher, frozen container recipe, baseline and tolerances stay intact.
The normal strict reference CI job is unchanged for ordinary PR/push runs.

Manually dispatch the existing `Reference container` workflow on the development
branch with `cpu_pair=true`. The diagnostic job succeeds only if both COMPATIBLE
atlases pass the strict reference and each mode repeats exactly. AUTO failures
are explicitly reported diagnostic outcomes, not hidden or reclassified as
reference passes. A green diagnostic is **not** a universal cross-CPU guarantee.

Success would support a separately reviewed, scoped compatibility-setting change
for this legacy CPU stack. It would not prove other datasets, processor families,
libraries or optimizer decisions unaffected. A failure means no claimed fix.

## Observed outcome

The initial two-job collection observed native Intel Xeon Platinum 8573C and
AMD EPYC 7763; no extra collection was needed. All eight atlases completed.
Intel AUTO passed only 8/10 in both repetitions; Intel COMPATIBLE and both AMD modes
passed 10/10 byte-identically in every repetition. Both modes repeated exactly
within each host, and COMPATIBLE outputs matched across hosts. Downloaded results
were independently verified; [all raw evidence and limits are retained](../reference/reference-cpu-full-pair-v1/README.md).
At the time of this retained observation, the normal launcher was unchanged.
The separately approved [contract 0.3 CPU launch policy](REFERENCE_CPU_LAUNCH_POLICY.md)
now sets COMPATIBLE for new legacy CPU commands. The diagnostic replaces that
single setting explicitly, preserving true AUTO observations and all other
arguments. Historical evidence above remains bound to producer commit 6113400.
