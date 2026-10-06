# v110 — reopen legacy numerical comparisons after starting qualification

A saved Stage 4 with predeclared integration tolerances could become unreadable
after **Check saved model** appended its new checkpoint declaration. The old
queue verifier expected only original timepoint candidates and legacy finer
resolutions. It rejected the independently declared qualification candidate,
blocking both continuation and the anatomy viewer with
`Numerical candidate queue differs from its declarations`.

The verifier now requires the exact reconstructed order: original candidates,
declared legacy resolutions, then independently declared qualification
checkpoints. Every new declaration, source, configuration and seed still passes
its own binding checks before the queue comparison. Missing, reordered or extra
rows remain rejected. Historical tolerances are preserved and do not qualify the
new protocol. No scientific settings, stopping rules or QC decisions are changed.

An already appended, unfinished declaration can resume through **Check saved
model**. It does not require deleting the attempt or restarting the pilot.
Completed earlier results and approvals remain intact; the new checkpoint still
requires its own numerical checks and anatomy review. Viewer preparation errors
also replace the busy status with the actual error instead of leaving a stale
"Preparing comparison" message.

Regression checks cover original and extended legacy comparisons, exact history
preservation, reopening, additional checkpoints, invalid queue order/coverage,
resumption of the existing declaration, fresh QC, completed qualification export
and artifact tampering. The saved owner study is inspected read-only; development
starts no private fit. Packaging, safe installation and native user acceptance
are separate from source tests. The v109 scientific-validation limitations remain.
