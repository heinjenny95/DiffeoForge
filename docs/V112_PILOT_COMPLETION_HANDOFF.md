# v112 — complete preview-reviewed pilots and return to atlas setup

Desktop preview QC is stored in a separate atomic, hash-chained review journal.
The v111 final-decision verifier read only the main engine event ledger. As a
result, a normal desktop approval could produce the selected configuration and
report, then fail to reopen with a misleading request to review that same fit.
The v111 regression helper used the older main-ledger QC route and missed this.

The verifier now reads both journals, verifies the chain and exact completed
output binding, and requires the actual recorded approval. The selection's
approval summary cannot replace a missing or mismatched human review. Existing
completed studies reopen without editing their events, outputs or decisions.
Repeating completion for the already-selected result returns the verified saved
completion without appending events; a different result remains blocked.

Finishing verifies and saves evidence in a background worker, with a visible
status and duplicate submission disabled. Successful explicit completion closes
the pilot window and invokes the existing main-window parameter application and
configuration review. It does not fit, shoot, start or approve a full atlas.
A reopened completed pilot also offers **Return to full atlas setup**. The parent
uses the freshly verified worker snapshot instead of repeating the expensive
completion verification immediately during this handoff.

Native convergence, fixed-state integration and anatomy retain their separate
meaning. Provisional/nonconverged warnings and full-cohort confirmation remain;
no threshold, scientific parameter, original result or QC approval is changed.

Regression coverage includes converged and capped preview QC, legacy receipts,
completion/reopening, unchanged repeated completion, missing reviews, changed
output bindings, explicit acknowledgement, background dispatch, duplicate clicks,
completed-window return and actual parent parameter application without an atlas
run. The owner's completed study is checked read-only; packaging and installation
are verified separately. Native first-use acceptance and scientific validation
remain open. This is a focused correction, not a full-suite validation claim.
