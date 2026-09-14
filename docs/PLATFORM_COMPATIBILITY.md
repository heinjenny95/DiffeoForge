# Public CPU platform compatibility checks

This is an engineering check of an installed Python wheel, not qualification of
native installers, biological results, performance or a Deformetrica replacement.
The protocol and tolerances below were declared before the first hosted run.

## Scope

| Target | Automated scope |
| --- | --- |
| Windows x64 | Desktop-only wheel/offscreen GUI; Modern CPU wheel and numerical observations |
| Linux x64 (Ubuntu 24.04) | Desktop-only wheel/offscreen GUI; Modern CPU wheel and numerical observations |
| macOS Apple Silicon (`macos-15`) | Desktop-only wheel/offscreen GUI; Modern CPU wheel and numerical observations |
| macOS Intel (`macos-15-intel`) | Desktop-only wheel/offscreen GUI; **no Modern engine claim** |

Official PyTorch macOS x86 binaries stopped after 2.2; the Modern engine requires
PyTorch >=2.6. The Intel GUI route therefore deliberately does not install Torch.
See the [upstream announcement](https://dev-discuss.pytorch.org/t/pytorch-macos-x86-builds-deprecation-starting-january-2024/1690).
Runner architectures are defined by
[GitHub's runner documentation](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The selected standard runners do not require owning a Mac. Real-user testing of
native installation, window interaction and platform integration remains open.

## Reproducible numerical protocol

`tools/platform_compatibility.py` runs only the six checked-in CC0 synthetic VTK
surfaces (five subjects and a template, each with 162 vertices), in a new directory
whose name contains spaces and a non-ASCII character. It accepts no private dataset
input. Python 3.12, PyTorch 2.13.0 and NumPy 2.5.1 are pinned in the CI matrix;
the reference backend and scientific analysis defaults are unchanged.

Each CPU platform independently verifies:

- A real subprocess worker completes a two-cycle, three-block L-BFGS atlas run.
- The saved workflow and atlas bundle pass strict verification and result reopen.
- A one-cycle parent plus one-cycle continuation matches the uninterrupted run
  within `atol=rtol=1e-12`, preserving optimizer continuation state.
- Dense and blockwise pairwise calculations agree within the cross-platform
  tolerances below.
- A separate worker accepts cooperative cancellation and publishes no result or
  private temporary run. This cancelled run is **not** represented as resumable;
  continuation is tested separately. Existing checkpoint-recovery tests also run.
- The checked-in synthetic fixture remains byte-identical.

The downstream comparison requires exactly Windows x64, Linux x64 and macOS arm64
observations from the same source commit, installed package bytes, fixture hashes,
engine version and numerical dependency versions. It verifies SHA-256 sidecars,
all local checks, finite numeric values and exact geometry/vector shapes.
All three platform pairs are compared, for dense, blockwise and continued runs.

The fixed symmetric criterion for every value is:

`abs(a - b) <= 1e-10 + 1e-8 * max(abs(a), abs(b))`

Compared fields are final template vertices, control points, momenta, reconstructed
vertices, objective/attachment/regularity and subject residuals. No PCA-axis sign
convention or biological conclusion is inferred from these small synthetic runs.
Tolerances must not be relaxed retrospectively to turn a failure into a pass.

Only compact JSON observations and their hashes are uploaded for 14 days. The full
temporary run tree stays on the runner; no private meshes, checkpoints, credentials
or installers are uploaded by this protocol. Missing or failed jobs do not count
as cross-platform success.

## Desktop-only regression and fixes

Remote-job and PCA-metadata modules now load optional Modern dependencies only
when those features are actually used. Previously their eager imports prevented
the reference-oriented GUI from opening without Torch. A subprocess smoke test
explicitly blocks Torch imports; desktop CI additionally installs only the desktop
extra and asserts that Torch is absent.

The GUI matrix covers offscreen construction, setup/review, worker lifecycle,
preview/proxy rendering, landmark editing and validation progress. A known Qt
offscreen `propagateSizeHints` diagnostic is allowed in the smoke test; any other
stderr still fails, except the separately allowlisted macOS `Sans Serif` font-alias
warmup diagnostic. Linux rendering dependencies are installed explicitly.

The first hosted pass exposed another eager Modern import in atlas comparison,
which prevented reference CLI startup without Torch. That import is now local to
the Modern PCA branch and a Torch-blocked CLI parser test covers the reference
route with the analysis extra. Three genuinely Modern-only test modules now skip
when Torch is absent and run explicitly in the Modern matrix. The reference
container host installs its required analysis extra; container engine versions
remain unchanged.
The full Python 3.11/3.13 suite also includes mixed reference/Modern qualification
tests and now installs the CPU Modern extra explicitly. Optional-engine absence
continues to be enforced by the independent desktop-only jobs and import-blocking
regressions; it is not inferred from this full-suite environment.

Apple Silicon initially passed 502 Modern tests but failed a legacy harness test's
extra `max_error < 2e-14` assertion, observing `2.220446049250313e-14` instead.
The actual fixture's declared `atol=1e-12, rtol=1e-10` checks already passed. The
extra observation-specific assertion now uses that **existing** fixture absolute
bound, with a negative test rejecting a `1e-6` objective perturbation. Neither the
reference fixture nor the new cross-platform protocol's tolerances were changed.

## Observation status

The first local targeted regression selection passed **121 tests, one expected
skip** (the missing-PySide6 branch is inapplicable where PySide6 is installed).
Hosted matrix execution and the cross-platform comparison are pending at this
implementation checkpoint. Results will be recorded with exact run/commit links;
configuration alone is not compatibility evidence.

Native `.dmg`/`.pkg` or Linux app packaging, clean-machine install/uninstall,
project preservation, signing, Deformetrica execution, Intel-Mac Modern engine,
GPU/MPS and large biological workloads remain separate qualification gates.
