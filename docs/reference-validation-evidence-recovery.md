# Recover Validation Lab evidence without rerunning an atlas

The Validation Lab's `elapsed` value describes the current backend run, not the
whole multi-run study. A terminal backend and a terminal validation evaluation
are separate events. In particular, a `run_failed` study event does not imply
that Deformetrica failed: inspect the attempt's `result.json` and lifecycle log.

## Small-triangle numerical correction

Metric numerics v0.2 removes an absolute machine-epsilon comparison against a
squared cross product (units of length to the fourth power). That comparison
misclassified valid small faces, notably in normalized high-resolution meshes.
The corrected calculation normalizes each triangle/edge locally, uses a unit
normal and oriented cross products, and avoids a cancellation-prone Gram
determinant. Coordinates, connectivity and scientific parameters are unchanged.

Genuinely collapsed faces/edges and non-finite coordinates still fail. No mesh is
repaired, deleted or silently excluded. The original deterministic samples
(at most 3,000 source vertices and 5,000 target triangles per direction), pooled
p95 and per-subject p95 are unchanged. These remain **sampled** distances, not a
claim of exact distance to every face of the full-resolution surface.

## 1. Export separate evidence while other runs continue

Use the corrected **source CLI** from the same checkout/runtime for export and
adoption. Do not replace an installed app while it has an active run.

```powershell
python -m diffeoforge reference-validation-evidence-export "PATH_TO_STUDY" `
  --run-id "EXACT_FROZEN_RUN_ID" --output "PATH_OUTSIDE_STUDY/recovered.json"
```

The exact selected run must have a terminal study failure and a successfully
completed backend. Recovery verifies the frozen design, source configuration,
cohort, protected inputs, all inventoried output hashes, terminal status and
logs. It computes evidence again and rechecks bindings before publishing a new
JSON plus SHA-256 sidecar. Progress is printed per subject. Existing destinations
are refused; source study events, meshes, checkpoints and run artifacts are never
written. Export may take minutes for large cohorts, but runs no optimizer.

The bundle records the original failure event, original attempt, source hashes,
metric version and exact metric-source hash. It is not an automatic QC release
or a completed study report. Record the printed SHA-256 independently for adoption.

## 2. Adopt only after the planned execution has ended

Do not restart the old installed Validation Lab on its failed entries: its older
runner can calculate new attempts. The corrected source runner skips backends
that already completed, allows other pending runs to proceed, and directs the
operator to evidence recovery without repeating the finished numerical work.

```powershell
python -m diffeoforge reference-validation-evidence-adopt "PATH_TO_STUDY" `
  "PATH_OUTSIDE_STUDY/recovered.json" --expect-sha256 "RECORDED_SHA256"
```

Adoption rejects any pending or unclosed started run, modified evidence, changed
source binding or metric implementation. This intentionally prevents adoption
alongside a legacy desktop writer; a partially attempted/cancelled study requires
operator review before adoption. New runners and adopters also share an exclusive
writer lock. A crash-left lock is not automatically removed: verify that no writer
is active before explicitly recovering it.

Adoption appends an audited completion for the **same attempt**, preserving the
original failure in history. Re-adopting the identical bundle is a no-op. Only
when all predeclared runs have evidence is the ordinary validation report
finalized. Fixed-template holdout, scientific validity gates and researcher QC
remain separate requirements. Never mix unreviewed outputs into an accepted study.

## Interrupted desktop with a final unfinished attempt

Before resuming, confirm that the desktop, its workers and the backend have all
stopped. Do not infer this merely from a closed window. Check the study ledger,
each attempt's terminal backend result, output inventory and input bindings;
preserve an external audit snapshot of those identities and the original ledger.

If completed backends are marked failed only because evaluation failed, and a
remaining run has an unclosed start but no successful backend result, use the
corrected source runner:

```powershell
python -m diffeoforge reference-validation-study-run "PATH_TO_STUDY"
```

It skips the numerically completed failed-evaluation attempts and assigns a new
attempt directory to unfinished work. An abandoned attempt is retained; this
route does not resume its optimizer checkpoint. Without a valid checkpoint, the
unfinished atlas starts again from its unchanged frozen configuration. Verify
the new `run_started` event and destination before treating restart as successful.

Keep the supervising source process alive; never start a second runner or reopen
the legacy Validation Lab to run the same study concurrently. At the end, an
`already completed ... recover evidence` CLI error (exit 2) can be expected for
the skipped earlier attempts: inspect the new backend result and terminal study
event separately. It does not itself mean that the replacement atlas failed.
Finish evidence export/adoption only after all planned attempts are terminal;
holdout work and scientific approval remain separate gates.

## Complete a recovery batch and continue to holdout

For several failed evaluations, keep one separate export and an independently
recorded digest per exact run ID. Read-only exports may be computed with bounded
CPU parallelism; do not run several study writers or atlas runners in parallel.
Review every export's identity, sample count, convergence, invalid-face count and
metric implementation before adoption. A computed result is not automatically
a passed validity gate. Keep the original ledger outside the study for comparison.

Adopt reviewed bundles sequentially with their recorded digests. Afterwards,
verify that every planned run has evidence, each recovered completion retains
its original attempt number, and the original ledger remains an unchanged prefix
of the appended history. Read `report/validation-report.json` and its HTML peer;
distinguish execution completion from the assessment's validity and stability
status. A numerical equivalence margin is not an anatomical threshold.

Once the training/resampling study is complete, the separate holdout stage is:

```powershell
python -m diffeoforge reference-holdout-study-init "PATH_TO_STUDY"
python -m diffeoforge reference-holdout-study-status "PATH_TO_STUDY/heldout-confirmation" --json
python -m diffeoforge reference-holdout-study-run "PATH_TO_STUDY/heldout-confirmation"
```

Initialization freezes the reserved subjects and each finalist's trained template
and control points from its **training-confirmation** run. Check these identities
and both freeze flags before starting the single supervised holdout runner. Do
not substitute a resample template, change finalists after inspecting holdout
results, or initialize over an existing holdout directory. The runner registers
the same reserved subjects against every frozen finalist; it does not retrain
the atlases. Report the holdout as pending until all registrations and their
separate assessment finish. Scientific QC and a later parameter-locked full-cohort
atlas remain separate decisions, not implicit consequences of recovery.

## Verification and scope

Regression coverage includes scale equivariance, thin triangles, true degeneracy,
non-finite coordinates, immutable export, active-study adoption refusal, output
tampering, changed source/bundle hashes, repeat adoption, CLI behavior and refusal
to rerun completed numerical work. The implementation, tests and documentation
were developed with Codex assistance and remain subject to human review.
