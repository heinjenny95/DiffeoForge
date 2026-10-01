# v98 — time-bounded surface-fit search

**Find fit** is a separate first-stage action for both existing and new pilots.
It preserves the old study and creates an independent study of the same selected
specimens. Default budget: 60 minutes; explicit alternatives: 15–240 minutes.
Opening a project starts nothing. The legacy grid remains available.

Four 40-iteration probes test baseline, broader, more local, and finer/stronger
matching. A generated template-covering control grid has at most 200 points,
rather than inheriting an inadequately sparse grid from a failed numerical leader.
Targets use separately hash-bound, topology-preserving scientific working copies
of approximately 20,000 faces. These are not display proxies. The original full
template topology remains unchanged; all original targets remain bound and available.
The screening template and control positions are fixed while learning the cohort's
fields. Confirmation restores the project's original freeze settings, normally
joint atlas optimization. This separates field initialization from template motion.

Each result is measured against all original targets using 2,048 area-stratified
samples per direction and MeshLab's unsigned point-to-triangle distance. Ranking
uses the worst normalized specimen p99, worst p95, and equal-specimen mean.
Sampled distances remain diagnostic geometry, not correspondence or anatomical
acceptance. Reports distinguish these measurements from legacy nearest-vertex QC.

The measured leader receives one 80-iteration finer-attachment/stronger-weight
probe with compatible learned template, controls and ordered momenta. The next
center cannot worsen another measured specimen's p95 or p99. One 200-iteration
confirmation then uses original target resolution and the selected learned state.
Optimizer step history restarts. No anatomical approval is generated. Screening
candidates cannot advance the stage, even if their optimizer converges.
Original-target confirmation still requires convergence and explicit visual QC.

One persistent budget is shared by the complete search and its successors. It
includes preparation in the first run and execution; a timer requests safe engine
cancellation at the remaining limit. Final noninterruptible geometry measurement,
file verification or preparation may finish after that limit. Reserving time before
execution makes crash recovery conservative; reopening cannot reset the budget or
automatically repeat confirmation. A lock prevents simultaneous execution of the
same search. Completed evidence and interrupted attempts remain separate.

This changes the search strategy; it does not guarantee a usable fit or a global
optimum. The full template can still make computation expensive. Working-target
approximation, sampled tails, nonlinear minima and shared-template compromises
remain limitations. No private parameter-tuning analysis or scientific fit is run
for this implementation. Prospective fit and first-use acceptance belong to the
researcher; package checks and synthetic regressions are separate evidence.

69 distinct scoped regressions passed across the affected batches, including real
MeshLab distance checks, complete synthetic search/confirmation control flow,
cohort/source binding, feedback, budget persistence/cancellation, legacy pilot
behavior, reports, GUI and execution lifecycle. Four affected tests were repeated.
These are not a private-data fit validation or a full-suite acceptance claim.

Proposed next step: one specimen at a time, pausing for human review before adding
the next. This is not implemented in v98. Approval of a fixed-template individual
probe cannot automatically approve a later shared-template atlas; joint cohort
confirmation and final review remain necessary.
