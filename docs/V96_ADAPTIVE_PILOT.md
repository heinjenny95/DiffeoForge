# v96 — bounded adaptive pilot search

The pilot can now run a feedback search after the current geometric stage, rather
than requiring the researcher to choose a center and repeatedly prepare fixed
neighbor batches. **Automatically improve fit** is enabled by default for ordinary
pilots. The explicit Run action starts it; loading a project starts no computation.
For a finished stage, **Improve fit automatically** starts the same search directly.
QC follow-up grids and the integration-accuracy stage retain their existing scope.

## Search and stop rules

- Choose a starting center by worst size-normalized specimen surface p95, then
  equal-specimen mean. Speed and deformation cost do not compensate for poor fit.
- Test continuation (more iterations and a tenfold tighter stopping tolerance,
  bounded below by 1e-10), lower noise, finer attachment detail, their interaction,
  more local/global deformation and denser control points.
- Reuse verified learned template, control points and ordered momenta when the
  spatial model is compatible. Kernel changes start zero momenta; denser-control
  tests also regenerate the grid. Optimizer step history is restarted. Template
  and control-point freeze settings are inherited, not silently enabled.
- Recenter only on measured improvement without worsening another specimen's
  p95 (floating-point slack only). Prefer the existing center on equal scores.
  The first relative step is twofold; later steps are square-root-of-two.
- Default limit: 12 added candidates, three rounds, 300 iterations per added
  candidate, per geometric stage. A round needs at least 1% improvement in worst
  or mean fit to continue. This is a search-progress heuristic, not a biological
  accuracy threshold. Stop on budget, plateau, specimen trade-off, missing valid
  evidence or exhausted bounds. Runtime failures require explicit retry.
- Existing series bounds remain fixed. A new series records bounds from one
  eighth to eight times its effective settings; only in-bound probes run. These
  are computational search limits, not empirically optimal biological ranges.

Each round creates a hash-bound successor. Prior candidates, runs and recorded
reviews remain accessible; reopening retains spent budget, source identities and
search decisions. Cancellation uses the existing controller. No automatic stage
selection, anatomical pass or full-cohort atlas launch is added. Iteration-capped
but finite valid results may seed more work; they do not pass convergence gates.

## Keeping the initialization through the workflow

After explicit approval, later pilot stages use the selected learned template and
compatible state, rather than silently discarding it. Changed spatial settings
reinitialize the field/grid. The final full-cohort configuration uses the selected
pilot's learned template and control points, with zero momenta for the full cohort
and the selected optimizer settings (at least the original full-run iteration cap).
This is a new shared full-cohort fit, not a splice of pilot fields or old PCA scores.
The final configuration records seed hashes and requires full-cohort QC.

Backend contract 0.4 adds optional bound initial momenta. Subject order, finite
values, header dimensions and control count must match exactly; plan/preparation
parity and protected-artifact verification cover the additional file. Historical
contracts 0.1–0.3 and completed study ledgers remain readable.

## Verification and limits

The scoped regression batch passed 103 tests; its one retained-evidence test
incorrectly expected historical contract 0.3 files to become 0.4. That expectation
was restored and passed in the 29-test adaptive follow-up. A further 68 plan,
metrics, report, presentation, build-version and warm-input tests passed; a new
stratified-successor fixture initially omitted required metric fields and then
passed after correction. The final 12 affected checks passed. These are scoped
checks, not a full-suite claim. An initial GUI batch was stopped after its stale
two-click test conflicted with the new direct-start action; the corrected GUI
regression passed.

Focused synthetic tests exercise selection, per-specimen regressions, repeated
rounds, budgets, plateau, cancellation, immutable source reuse, tamper rejection,
next-stage seed transfer, final-cohort initialization, dialog actions and preparation
parity. The existing Deformetrica 4.3.0 runtime completed a five-subject synthetic
cold/warm pair (two optimizer iterations each, 36 controls, torch CPU), explicitly
loading the saved 5 x 36 x 3 momenta. This verifies runtime input compatibility,
not fit quality. A first test driver misread the integer exit code as a result
object after a successful cold run; the corrected driver reused that completed
run without recomputing it. The themed pilot was inspected on synthetic results.

The fit metric remains sampled bidirectional nearest-vertex p95. It cannot prove
local anatomy, correspondence or absence of self-intersection. Strict specimen
protection can stop at a trade-off that a researcher would accept. This bounded
pattern search is not a global optimizer and does not establish universally
correct parameters or reproduce a private diagnostic protocol. No new private
scientific fit or full atlas was run for this implementation. Prospective fit
quality and independent first-use acceptance remain open.

Build, installation and distribution identities are recorded separately.
