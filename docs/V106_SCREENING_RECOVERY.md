# v106 — prepare and recover single-specimen screens

Cold single-specimen screens have seven mandatory protected files: two
configurations, one reference, one target and three engine XML files. The run
manifest previously required eight even for a legitimate frozen singleton,
stopping preparation before Deformetrica started. The singleton branch now
accepts seven; ordinary multi-subject runs still require at least eight. Frozen
reference/control settings, declared singleton scope and artifact hashes remain
required. Learned fields and their compatibility adapter remain protected when
present.

Technical screening failures are separate from human rejection. Stage 2/3 shows
their count, folded error details and **Retry technically failed screens**. That
action requeues only those failures without running an optimizer. **Test next
option** then creates a new immutable attempt. Previous failed attempts remain
verified, as do accepted/rejected screen decisions and the retained joint fit.
Screens still need their own visual decision; keeping a screen does not approve
the joint atlas. Stage 4 and convergence criteria are unchanged.

Regression coverage includes real cold-singleton run preparation, missing-file
and non-singleton manifest rejection, frozen-reference/scope guards, retry and
reopening, preserved decisions/output, historical-evidence tampering and desktop
dispatch/counts. Synthetic engineering inputs only; no private fit, parameter
tuning or scientific approval is performed. Prospective anatomical acceptance
and runtime savings remain user checks. Drive upload remains request-only.

Verification: 79 scoped cases passed across the final applicable checks, plus
seven installer-contract cases. The wider run passed 78 cases and exposed an
incorrect input-directory attribute in the new test fixture; that fixture was
corrected and its real preparation test rerun successfully. The final focused
set passed nine cases, including the expanded background-retry path and installer
contracts. Ruff, compilation and diff checks passed. This is scoped engineering
verification, not independent scientific or complete-project qualification.
