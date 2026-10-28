# Retained pilot completion and retry

A pilot can retain the same approved joint fit through deformation, noise and
time-resolution stages. Completing that path records one actual optimizer timing,
not three duplicate observations. The configuration schema accepts that evidence;
the runtime estimator continues to use its broad engineering estimate until at
least three usable measurements exist. No optimizer, tolerance, integration rule
or iteration-budget policy changes in this repair.

Final-decision verification follows the retained-output chain to its original
bound human review, including later withdrawals. A stage-selection summary cannot
substitute for that review. The reconstruction, cohort, integration receipt and
source hashes remain checked.

If final serialization fails after the owner's decision was recorded, reopening
returns the same saved fit to the finish screen. Retrying reuses that exact
decision and verifies any existing seed, configuration and report before reuse.
Different existing bytes are rejected rather than overwritten. Completed finish
calls remain idempotent. No fit or numerical check needs restarting.

Regression checks cover a single optimized joint candidate retained through all
later stages, inherited preview approval, missing approval, injected schema,
report and completion-ledger failures, repeated finish and sparse timing estimates.
Real project checks are read-only; packaging and installation qualification are
tracked separately. Scientific success and full-cohort anatomical approval remain
separate from successful pilot serialization.
