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

## Verification and scope

Regression coverage includes scale equivariance, thin triangles, true degeneracy,
non-finite coordinates, immutable export, active-study adoption refusal, output
tampering, changed source/bundle hashes, repeat adoption, CLI behavior and refusal
to rerun completed numerical work. The implementation, tests and documentation
were developed with Codex assistance and remain subject to human review.
