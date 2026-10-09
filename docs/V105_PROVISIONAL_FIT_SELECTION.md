# v105 — explicit provisional selection after an iteration limit

A completed joint fit can preserve anatomy while still reaching the optimizer's
iteration limit. In stages 1–3, **Use approved fit provisionally → stage N** now
offers an explicit way to explore the next parameters after bound whole-pilot
visual approval. Selecting it records the decision and prepares the next stage;
it does not launch another fit or change convergence evidence. Missing or invalid
reconstructions, incomplete per-specimen measurements, other stop signals,
singleton screens and withdrawn/unrecorded visual approval remain blockers.

The selected run remains non-converged and excluded from numerical ranking and
automatic selection. The append-only decision records the provisional mode,
verified output binding and limitation. Stages 2/3 retain the exact saved output
and its real prior approval as a baseline. Keeping that baseline without a new
fit carries the provisional record forward; it cannot drop the warning or restore
a withdrawn approval. New optimized results need their own visual decision.

Stage 4 has no iteration-limit exception: convergence, complete numerical
comparison and anatomical approval are still required before finishing. Reports
and final configuration provenance explicitly list any provisional selections in
earlier stages. A visually accepted fit does not establish stable momenta or
morphospace; a new full-cohort atlas and QC remain required.

Synthetic regression tests cover explicit versus ordinary selection, persistence,
unchanged fits/receipts, missing QC, other failures, correct stop evidence,
retention through stages 2/3, warning tampering and approval withdrawal, strict
stage 4, report/export provenance and background desktop dispatch without an
optimizer. Existing retention, screening, study, dialog and version contract
suites are checked separately. No private fit, parameter tuning or scientific
approval is part of this update. Drive distribution remains request-only.

Final scoped sets passed: 64 pilot/desktop/version cases and seven installer
contract cases. Ruff, compilation and diff checks passed. See
[verified build and separate installation state](V105_DELIVERY.md).
