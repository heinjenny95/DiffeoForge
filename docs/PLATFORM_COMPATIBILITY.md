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
Windows-branch unit tests now replace only the tested module's OS facade, rather
than modifying global `os.name` and breaking Linux pytest/pathlib itself. WSL path
translation has separate drive/space/Unicode/network-share tests; these mocked
tests do not claim real WSL or GPU execution on Linux/macOS.
Five GUI-only tests now skip individually when Qt is absent, preserving their
headless numerical peers. All five are explicitly exercised by the Qt-equipped
desktop matrix, including the Validation Lab first-iteration/progress case.

Apple Silicon initially passed 502 Modern tests but failed a legacy harness test's
extra `max_error < 2e-14` assertion, observing `2.220446049250313e-14` instead.
The actual fixture's declared `atol=1e-12, rtol=1e-10` checks already passed. The
extra observation-specific assertion now uses that **existing** fixture absolute
bound, with a negative test rejecting a `1e-6` objective perturbation. Neither the
reference fixture nor the new cross-platform protocol's tolerances were changed.
The Python 3.13 full suite subsequently exposed a second legacy bit-equality
assertion in the saved-tensor memory test: standard/recomputed objective differed
by `1.7764e-13` (relative `3.9921e-14`). That assertion now uses the same module's
pre-existing forward parity bounds (`rtol=2e-12, atol=2e-13`), while gradient and
memory-payload checks remain unchanged. The entire blockwise-objective test module
is now also included in every Modern platform job. This is a documented test
contract correction, not an engine change or a relaxation of either frozen
reference-container or cross-platform observation tolerances.

## Observation status

The first local targeted regression selection passed **121 tests, one expected
skip** (the missing-PySide6 branch is inapplicable where PySide6 is installed).
The final local changed-area regression selection passed **106 tests, one expected
skip**; isolated OS mocks and WSL path cases passed another **16 tests**. A wheel
was built/verified and installed into a separate local test directory; its full
synthetic worker/reopen/continuation/dense-blockwise/cancellation observation passed.

The first complete platform matrix at development head `727dcd2` passed all seven
platform jobs: **521 Modern tests per CPU platform** and **197 desktop tests on
Windows / 190 on each other GUI platform**, with expected platform/optional skips.
The three-pair numerical comparison passed and was independently recomputed
byte-for-byte locally. Exact public observations, hashes, source checkout identity,
job counts and limitations are retained in
[`reference/platform-compatibility-v1`](../reference/platform-compatibility-v1/README.md).
Maximum absolute objective difference was `7.11e-13`; reconstructed coordinates
differed by at most `1.34e-15` on this unitless fixture.

That first CI run's separate full-suite jobs failed during collection. The final
[CI run 34827124063](https://github.com/heinjenny95/DiffeoForge/actions/runs/34827124063)
at development head `e1358b84c8b31ff65cd5c6de8c6abc96b2af29b3` now passes **all ten
jobs**: **1,432 passed / 114 expected skips** on each full Python 3.11/3.13 suite,
**537 Modern tests per CPU platform**, **198 desktop tests on Windows / 191 on each
other GUI platform** (14/21 expected skips), plus the three-pair comparison.
Both full-suite wheel/sdist builds and wheel-content checks passed. The skips
cover unavailable Qt in full-suite jobs and optional/platform-specific cases;
the separate desktop jobs exercise Qt with Torch explicitly absent.

Final observations are retained under `reference/platform-compatibility-v1/final-ci`.
Independent local recomparison again reproduced the hosted report bytes exactly
(SHA-256 `8e5b2162b00e934ce1a7bdccff92f3fbae8db0bdb268a486214ec1d8dda071f9`).
The final maximum differences were `7.11e-13` for objective components and
`1.78e-15` for reconstructed coordinates. These are observations for this small
unitless fixture, not universal error bounds. The separate legacy container gate
below had failed and is **not** included in this ten-job CI success.

Native `.dmg`/`.pkg` or Linux app packaging, clean-machine install/uninstall,
project preservation, signing, Deformetrica execution, Intel-Mac Modern engine,
GPU/MPS and large biological workloads remain separate qualification gates.

### Separate legacy reference-container gate remains unresolved

After correcting its host analysis dependency,
[reference-container run 34825794638](https://github.com/heinjenny95/DiffeoForge/actions/runs/34825794638)
executed the frozen Deformetrica 4.3.0 CPU image but passed only **8 of 10** existing
synthetic reference artifacts. Control points, momenta, template and five
reconstructions were byte-identical. Convergence values differed by up to `1e-3`
(RMS `1.3673e-4`); residuals differed by up to `9.5368e-7` (RMS `4.7684e-7`).
The gate's frozen `max=1e-6, RMS=1e-7` contract was not changed. Cause and scientific
implications are not established by this platform package. This failure must be
investigated separately, not hidden by the successful Modern CPU comparison or a
reference-baseline/tolerance reset.

Follow-up: an instrumented AMD clean-runner execution passed 10/10 without a
numeric fix, while isolated legacy-library dispatch changes reproduce the same
geometry-pass/scalar-fail pattern locally. The cross-CPU gate remains unresolved,
not permanently red or fixed. See [the CPU investigation](REFERENCE_CPU_DIAGNOSTICS.md).

### Follow-up worker-start race

[CI 34829353499](https://github.com/heinjenny95/DiffeoForge/actions/runs/34829353499)
exposed an Intel-Mac timing case: a child could exit before the launch request was
written, producing a generic supervision error instead of the typed process error.
The request-write boundary now reports `DesktopWorkerProcessError`, drains bounded
stderr and retains cleanup/fail-closed behavior. A deterministic early-exit test
covers the race. Fake event-stream workers now consume the request first so their
tests actually reach the intended protocol check. No engine arithmetic changed.

[CI 34831998635](https://github.com/heinjenny95/DiffeoForge/actions/runs/34831998635)
at `0b555d83f587aed8fd4a11d19aa627d3dd06f3fd` subsequently passed all ten jobs:
1,459 tests / 114 skipped on both Python 3.11 and 3.13; 538 Modern tests on each
of Windows, Linux and Apple Silicon; the four-platform optional-engine-free GUI
matrix and three-platform synthetic numeric agreement. The separate contemporaneous
legacy reference job failed on a real Intel Xeon 8370C (8/10) and retained the
scalar-reduction evidence described in the CPU investigation. These two workflow
outcomes must not be collapsed into a claim that all engine gates are green.

### Later Intel-Mac GUI observation remains open

[CI 34834843155](https://github.com/heinjenny95/DiffeoForge/actions/runs/34834843155)
at `6113400c29f73a11b81a62ead80b2da1d5efbe2b` passed nine jobs, including both
1,469-test host suites and all three Modern CPU jobs, but the optional-engine-free
Intel-Mac GUI process exited with a native segmentation fault (139), near the
surface-rendering test boundary. The traceback does not establish its cause.
No desktop or engine implementation changed in this commit. Preserve this failed
observation and isolate the GUI lifetime/threading/native-library issue separately;
do not call the complete platform matrix green or suppress the test.

The subsequent [renderer lifetime investigation](DESKTOP_RENDER_LIFETIME.md)
reproduced a native Windows crash with only the five surface-render tests and
replaced the worker-owned signal object with a Python mailbox/GUI-thread timer.
The repaired local full suite passed 1,601 tests with seven skips; the final
ten-case renderer suite passed 20 repetitions, including 2,000 explicit owner
destruction cycles. [CI 34839397593](https://github.com/heinjenny95/DiffeoForge/actions/runs/34839397593)
at `6e5eb99bc1f2662a2532f01a0114a8814df8f20e` passed all ten jobs, including all
four desktop platforms. The baseline full suite also passed on a separate run,
so this remains an intermittent-failure investigation, not a deterministic
full-suite before/after comparison.
The historical Intel-Mac observation is preserved without asserting an unobserved
native stack or inferring its cause solely from a later green run.
