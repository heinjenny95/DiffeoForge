# v136 — use a finer saved evaluation without refitting

Stage 4 can adopt the finer evaluation of an unchanged saved deformation field
when the existing finer-grid comparison passes for every pilot specimen. The
primary action names that grid and explicitly says **no refit**. The original
two evaluations are reused; only the missing third nested grid is computed.
Integration equations, complete-cohort checks and thresholds stay unchanged.
Choosing adoption can explicitly retire a queued optimizer check that has never
started. Its declaration remains in history; it cannot later resume implicitly.
A check that has already started requires a separate decision and is preserved.

The adoption is a distinct immutable evaluation candidate. Its provenance binds
the original optimizer result, learned template, control points, ordered momenta,
configuration, grid receipts and every endpoint. The saved optimizer history
remains attached to its original grid. No optimizer iteration, convergence signal,
likelihood or fit metric is invented at the new grid. A cancelled evaluation does
not register a partially completed fit, and reopening verifies bound evidence.

The new evaluated reconstructions require their own human anatomy review. A
passed grid check never transfers a prior visual approval. Finishing requires an
explicit provisional decision; the final configuration carries the evaluated
time grid and original-field provenance into a new full-cohort atlas. This is a
pilot starting point, not proof of optimizer stability or biological validity.
Optional refitting remains a separate action.

Verification covers reuse of two grids with only one new Shooting call, original
bytes and review preservation, distinct evaluated QC surfaces, provisional finish
and reopen, changed-artifact rejection, cancellation and an individual specimen
failure. Native execution, packaged UI, installation and independent first use
remain separate evidence gates.
