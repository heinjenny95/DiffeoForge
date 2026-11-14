# v94 — specimen fit before pilot advancement

The earlier geometric-stage score independently min-max normalized residuals,
sampling sensitivity, deformation/area proxies and runtime. A fast underfit could
outrank a much closer reconstruction; weight stability did not establish anatomy.

The attachment, deformation and noise stages now order eligible options by:

1. The largest per-specimen p95 distance divided by that original's bounding-box diagonal.
2. The equal-specimen mean of these normalized distances.
3. Pooled distance, only for an exact tie.

Runtime, deformation cost, area change and interleaved-sample sensitivity remain
diagnostics and cannot compensate for poor fit. No candidate-range min-max
normalization or universal anatomical pass threshold is used. The existing
deterministic, symmetric nearest-vertex distance is explicitly a sampled QC proxy,
not point-to-triangle distance, homologous correspondence or the attachment
objective. Small features below p95 or sampling resolution still need inspection.
Size normalization supports comparison across unequal specimen sizes; it is not
a biologically calibrated importance weighting. An overall-fit favorite can differ
from the smallest worst-specimen-distance option, so the UI calls this a review
shortlist and retains manual choice. The integration stage separately compares
numerical discretization; it shares the mandatory anatomical gate.

## Review and continuation

Original-detail display is necessary but no longer counts as acceptance. Each
specimen receives pass/fail/uncertain. All specimens must pass before candidate
approval; an inspected failure can be recorded immediately without opening every
remaining specimen. Decisions, optional study-specific observations and notes are
bound to completed evidence. Saved failure cannot be overridden by a caller's
boolean approval. Manual, provisional and automatic selection share the gate.

Each batch now stops after its current stage. Historical AFK authorization cannot
advance unreviewed stages, and the old unattended-advance controls are hidden.
Existing completed studies, frozen assessments and reports remain readable and
are not retroactively approved or rewritten. Legacy individual residuals are
normalized read-only against bound original geometry; missing specimen evidence
fails closed. The existing appearance and independent minimizable window remain.

## Local fit refinement

An inspected, numerically valid option may be used as an exploration center even
when visually rejected. **Refine fit** previews at most eight new options: half
and double each of attachment width, deformation width, control-point spacing and
noise standard deviation, one axis at a time. Exact settings already present are
not repeated. This allows the noise setting to be explored before accepting an
inadequate first stage. Iteration caps, original template and entire pilot cohort
remain unchanged. Finite parameter bounds are recorded; inherited series bounds
cannot silently widen. There is no recursive expansion or guarantee that this
local grid will solve a difficult registration.

A separate successor preserves completed metrics, source hashes and visual
decisions. Verified links open the original reconstruction evidence for retained
options, including across successive extensions. Preparing a successor does not
start the engine; Run calculates only pending options. No specimen is dropped,
no result is spliced into an atlas, and source studies remain unchanged. If the
local comparison is inadequate, review alignment and template suitability before
further scientific runs. Every chosen option still requires every-specimen QC.

## Verification and limits

Regression coverage includes adverse fit/economy trade-offs, hidden individual
failures, unit changes, missing evidence, persisted approval and early rejection,
non-bypassable selection, current-stage batch pause, fixed-cohort successors,
preserved reconstruction access, run reuse, parameter bounds, completed-report
production and offscreen UI review/refinement. Historical tests requiring automatic
advancement without anatomical acceptance were replaced by the new gate tests;
source binding, retry, cancellation and existing report checks remain applicable.
Private completed evidence is inspected read-only; no new scientific run or
anatomical acceptance is supplied by this software update. Full-cohort atlas QC,
scientific validation and external usability remain separate work.

Verification covers 113 scoped regression cases across the main run and affected
reruns, plus Ruff and synthetic offscreen layout/minimize checks. The full run
passed 111 cases; one outdated guidance-text assertion was updated and passed
its focused rerun, and an additional outward-policy regression passed. The final
UI changes passed all seven affected dialog/lifecycle cases. A broad QC test
exposed a removed early guard; its temporary synthetic engine jobs ended, the
guard was restored, and an unstubbed-engine tripwire now protects that test suite.
No private pilot or atlas was executed or changed.

Source version, installation and Drive distribution are tracked separately.
