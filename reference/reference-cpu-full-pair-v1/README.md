# Full-atlas Intel/AMD compatibility observation

14 September 2026. **COMPATIBLE resolves the observed Intel scalar discrepancy
for this frozen public fixture and preserves the AMD result.** This is a scoped
experimental finding, not a changed production default or universal CPU guarantee.

[Prospective protocol](../../docs/REFERENCE_CPU_FULL_PAIR.md) ·
[Completed two-host diagnostic CI](https://github.com/heinjenny95/DiffeoForge/actions/runs/34834836569) ·
[Observer source 6113400](https://github.com/heinjenny95/DiffeoForge/commit/6113400c29f73a11b81a62ead80b2da1d5efbe2b)

## All eight complete atlases

Each cell below covers **two independent full-atlas runs**, in fresh containers.
Both modes repeated byte-identically on each host.

| Actual host CPU | AUTO | COMPATIBLE |
| --- | --- | --- |
| Intel Xeon Platinum 8573C | 8/10 artifacts pass in both runs; those eight byte-identical | 10/10 pass in both runs, all byte-identical |
| AMD EPYC 7763 | 10/10 pass in both runs, all byte-identical | 10/10 pass in both runs, all byte-identical |

Intel AUTO again fails only convergence and residuals. Convergence maximum
absolute difference is `0.0009999999999998899`, RMS `0.00013673204516100583`
(25 changed values); residual maximum is `9.536800000000366e-7`, RMS
`4.768380000167927e-7` (two changed values). These match the historical failure
statistics. Control points, momenta, template and five reconstructed surfaces
remain byte-identical. No maximum (`1e-6`) or RMS (`1e-7`) threshold was relaxed.

COMPATIBLE produces zero difference for **all ten** artifacts on both CPUs.
The cross-host COMPATIBLE static probes also match exactly, including all
operand hashes, float32/float64 dot terms and static gradient hashes. Every probe
used four Torch threads. Generated model/data/optimization XML, observer hash,
source commit and Torch build configuration match across hosts.

## Retention and independent checks

- `intel-xeon-8573c/`: Ubuntu 22.04 hosted job; four atlas observations, two probes.
- `amd-epyc-7763/`: Ubuntu 24.04 hosted job; four atlas observations, two probes.
- Each directory has `report.json` / `report.sha256`, plus 58 hash-inventoried
  public output/XML/log/probe files. No private meshes or pickle checkpoints.
- Reports preserve exact commands, actual CPU model/vendor, independently built
  image IDs, configuration/reference hashes and all failed as well as passed
  comparisons. The image IDs differ; no bitwise-identical image-build claim is made.
- After download, the Windows host independently rederived every comparison from
  the original retained bytes, verified hashes, XML identity and repeatability.
  The retained-evidence test repeats this check and requires both native vendors.
- `.gitattributes` disables newline/whitespace normalization for these raw bytes.
  Git object hashes are checked against the downloaded files before final handoff.

```powershell
python tools/observe_reference_cpu_pair.py verify --repository . --directory reference/reference-cpu-full-pair-v1/intel-xeon-8573c
python tools/observe_reference_cpu_pair.py verify --repository . --directory reference/reference-cpu-full-pair-v1/amd-epyc-7763
```

## Interpretation and remaining boundary

Within each host, the only numerical launch-setting difference is `MKL_CBWR`;
the mode order was AUTO, COMPATIBLE, COMPATIBLE, AUTO. The complete output now
supports the earlier scalar-reduction diagnosis beyond a static probe.

This supports a **separately reviewed, explicitly recorded compatibility setting
for this legacy CPU stack**. It does not prove all CPUs, instruction sets,
libraries, datasets or near-boundary optimizer decisions equivalent. There is
one synthetic cohort and two host models; the hosts also differ in OS/kernel,
so this is not a CPU-only factorial study. Elapsed times include compilation
and are not a matched performance benchmark.

No engine equations, reference bytes, tolerances, installed application or
research projects changed. The ordinary default reference CI remains strict
and can still fail on Intel until a scoped product/configuration change is made.
Separately, the contemporaneous general CI had a native Intel-Mac GUI crash;
see [platform status](../../docs/PLATFORM_COMPATIBILITY.md). A successful numeric
diagnostic must not conceal that unrelated open platform observation.
