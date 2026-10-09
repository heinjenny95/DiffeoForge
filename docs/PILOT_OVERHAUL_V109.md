# Pilot v109: fit search and independently qualified numerical evidence

The pilot's purpose is a defensible, repeatable parameter recommendation within
the explored domain. It cannot promise a unique optimum or anatomical correctness.
Software checks, human anatomy decisions and scientific validation are separate.

## Acceptance contract

- Keep the one-specimen feedback loop: rejection changes that specimen's trial,
  acceptance advances, Maybe retains a recoverable fallback. Joint optimization
  has separate all-specimen QC. Never splice independent fields into analysis.
- Preserve approved joint baselines through spatial/weight comparisons. Explain
  retained, screened, rejected, running and newly completed results consistently.
  The fit-first distance order is a review suggestion, not an anatomical winner.
- Show why an option cannot advance and the specific next action. Report sampled
  geometric distances in coordinate units and normalized scale, not as anatomical
  accuracy percentages. Runtime and regularity cannot outweigh failed anatomy.
- Final qualification separates optimizer stability from integration error.
  Declare the source and criteria before any new computation. Continue one saved
  joint model with a tighter stopping criterion and a finite iteration budget,
  measuring template/reconstruction movement, objective change and velocity-field
  change on common probes. This is a local stability check, not a global optimum.
- Evaluate the resulting single learned model by endpoint-only Deformetrica
  Shooting at N, 2N-1 and 4N-3 timepoints: template, controls, momenta, cohort,
  deformation kernel, precision and integration scheme remain identical. Bind
  every output and verify source-count round-trip and ordered topology. Compare
  corresponding points for every specimen against its own scale. Do not compare
  independently refitted atlases as pure integration-error evidence.
- A stable source count can be recommended only after the independent optimizer
  and integration checks pass. The newly optimized checkpoint requires its own
  human QC. A finite unsuccessful check reports the failed gate and preserves its
  improved checkpoint; it does not force a winner, relax tolerances or loop forever.
- Old studies and decisions retain their meaning. Explicitly starting the new
  qualification adds a new protocol and immutable checkpoint/receipt; never edit
  earlier configurations, runs, comparisons, thresholds or approvals.
- Clear phase, stage, option, specimen, elapsed time and iteration/cap; no invented
  ETA. Notify once when a new human decision is needed, including while minimized,
  without forcing focus. A click returns to the pilot. Close/cancel releases every
  terminal worker; completed results remain reviewable during a different run.
- Export the complete search/decision history, qualification protocol, criteria,
  source and artifact hashes, backend identity, failed gates and limitations.
  Full-cohort confirmation and independent anatomical/shape-space validation remain
  required; passing the pilot is not publication-level biological validation.

## Verification

Use meaningful synthetic regressions and the actual installed reference runtime
on public synthetic data. Verify fixed-state identity, timepoint counts, endpoint
round-trip, nonlinear deformation, every-subject checks, independent optimizer
failures, tampering, reopening, cancellation, UI transitions and notification
deduplication. Private data may be inspected read-only; no private fit is run for
development. Build/install evidence and owner anatomical acceptance are separate.

Verified source checks: 50 study/retention/integration regressions and 32
qualification/UI/lifecycle/Plan-B regressions passed. The expanded final
qualification suite passed 15 tests; subsequent focused checks passed for the
common-probe field comparison, notification/progress behavior and the new Stage 4
actions. They exercise prospective criteria, immutable initialization, complete
per-specimen checks, fresh QC, completed-report reopening, audit export and
artifact tampering. These counts overlap; they are not a combined test total.

The actual Deformetrica reference runtime passed public, three-specimen nonlinear
Shooting audits with CPU Torch Euler, CUDA KeOps Euler and CPU Torch RK2. At the
source count (5), all corresponding endpoints reproduced the fitted endpoints
exactly in these examples. The 9-to-17 differences were smaller than the 5-to-9
differences for every specimen. An actual WSL test verified that loss of the
parent's input pipe terminates the owned adapter with exit 130. This is runtime
identity/cancellation evidence, not scientific validation of a private dataset.

The new endpoint-only adapter supports native and WSL reference launchers;
developer-container qualification requires a separate implementation and test.
No wall-clock deadline is added. One check has a finite optimizer iteration
budget (100 by default), and fixed-state Shooting still depends on model size.
Native notification visibility and independent first-use acceptance remain open.

## Resuming a saved pilot

Open the existing saved fit search. Stages 1–3 preserve their original decisions
and approved joint baselines; a new pilot retains the specimen-by-specimen search
and early Stage 2/3 screens. In Stage 4, select the saved joint fit and use
**Check saved model**. This appends one tighter checkpoint and its prospective
protocol, then checks that single state on N, 2N-1 and 4N-3 grids. Review the new
checkpoint; **Use approved option and finish pilot** becomes available only if
its independent numerical gates and fresh anatomy review pass.

If optimizer stability fails, continue the saved checkpoint explicitly. If
integration fails, **Refit a finer model** makes one warm fit at 2N-1; review it
and qualify it separately. Neither action deletes prior fits or changes criteria.
The audit export includes joint lineage, individual trials, decisions, Plan B,
runtime identities and verified qualification receipts, including after completion.

Primary basis: [Deformetrica model parameters](https://gitlab.com/icm-institute/aramislab/deformetrica/-/wikis/3_user_manual/3.2_model_xml_file),
[optimization parameters](https://gitlab.com/icm-institute/aramislab/deformetrica/-/wikis/3_user_manual/3.4_optimization_parameters_xml_file),
and [Bône et al., Deformetrica 4](https://inria.hal.science/hal-01874752).
Defaults are prospective engineering criteria; independent scientific threshold
validation remains open. They must not be tuned retrospectively to pass one study.
