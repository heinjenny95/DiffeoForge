# Legacy CPU numerical-reference investigation

14 September 2026. **Environment-dependent behavior reproduced; no numerical
engine fix or cross-CPU acceptance claimed.** Frozen reference bytes and both
existing thresholds remain unchanged.

## Observations

1. Several clean-container CI executions reported 8/10 artifacts passing: exact
   control points, momenta, template and five reconstructions, but different
   convergence/residual numbers. One retained failed log reports convergence
   max `0.001`, RMS `0.000136732`; residual max `9.5368e-7`, RMS `4.76838e-7`.
   [Original failed run](https://github.com/heinjenny95/DiffeoForge/actions/runs/34828033160).
2. The same public input and frozen CPU-wheel stack on the local AMD Ryzen 9 7950X
   passed 10/10, all bytes identical. An additional isolated `MKL_CBWR=COMPATIBLE`
   run also passed unchanged. No input/model/optimizer setting changed.
3. The newly instrumented clean-container run on an AMD EPYC 7763 also passed
   10/10 without a numerical fix. Its static reduction operands and gradients
   matched the local probe. Thus the earlier failure is not a persistent source
   regression that the new instrumentation fixed.
   [Diagnostic CI](https://github.com/heinjenny95/DiffeoForge/actions/runs/34829353422).
4. A deliberately isolated legacy-library dispatch experiment
   (`MKL_DEBUG_CPU_TYPE=5`, **diagnostic only, not a supported product setting**)
   changed float32 `torch.dot` results even though both dot-operand hashes and
   all five static source-gradient hashes remained identical. Dot terms changed
   in increments of `4.76837158203125e-7`; float64 reductions of the same operands
   differed by at most `8.88e-16`. This locates the controlled difference after
   the KeOps convolution, at the final scalar reduction.
5. With that diagnostic override, a complete atlas again passed exactly the eight
   geometry/parameter artifacts and failed the two scalar/log artifacts:
   convergence max `0.0004`, RMS `9.02894e-5`; residual max `9.5368e-7`, RMS
   `6.03157e-7`. Adding `MKL_CBWR=COMPATIBLE` did **not** rescue that artificial
   override. No compatibility flag has therefore been added to production or
   the frozen image on the strength of this experiment.

The controlled experiment reproduces the **class** of failure, not every number
from the original CI. That old runner's CPU/reduction operands were not retained,
so its exact low-level dispatch remains unproven. Do not claim native Intel
qualification from an artificial dispatch override on an AMD host.

## Why values can differ while shapes remain identical

The upstream Current attachment evaluates a residual as
`source_self + target_self - 2 * cross`. Subtracting these float32 scalar terms
can amplify their last-bit rounding relative to a small residual. The derivative
of a dot product need not depend on its rounded scalar result, so the observed
identical gradients are consistent with the changed objective values. The CLI
then prints only four significant digits (`%.3E`), which can turn a small numeric
change into a larger difference between adjacent printed log values.

This is an interpretation supported by inspected Deformetrica 4.3.0 source and
the controlled operand/gradient experiment, **not proof that other datasets or
optimizer trajectories are unaffected**. Near a line-search or stopping boundary,
different values could matter. The strict test must continue to report failure.

Intel documents processor-dependent dispatch and conditional reproducibility,
but these facilities must be verified for the actual legacy stack; they are not
an automatic guarantee for this test:
[Intel CNR guidance](https://www.intel.com/content/www/us/en/docs/onemkl/developer-guide-linux/2023-1/get-started-with-conditional-num-reproducibility.html).

## Implemented diagnostic improvements

- `compare-reference` now reports separate maximum/RMS pass flags, the count of
  changed values and at most five largest discrepancies, including CSV row and
  column. Numeric acceptance logic, tolerance values and source artifacts are intact.
- Backend environment receipts include CPU model and an explicit allowlist of
  numerical environment variables. These are **probe-process** values; the run's
  configured threads and actual launch environment remain separate provenance.
  Credentials and unrelated environment variables are never enumerated.
- CI retains the bounded public convergence/log/residual and reduction-probe
  evidence even on failure. The probe accepts only the hash-checked six CC0 files.
  New probes explicitly use four Torch threads after Deformetrica imports.

## Next acceptance boundary

Retain an actual failing runner's complete diagnostic evidence and compare it
against a passing runner before proposing any backend arithmetic change or
cross-CPU tolerance study. A passing AMD run is useful, but does not close that
gate. Separately evaluate the Modern float64 engine using the prospective
[public paired protocol](PUBLIC_ENGINE_PAIR.md); do not conflate that experiment
with this float32 legacy-CLI reference or claim biological parameter validity.
