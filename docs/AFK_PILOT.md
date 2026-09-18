# Bounded AFK / overnight pilot

AFK is an opt-in alternative to the standard robustness-gated automatic pilot.
Check the AFK option and explicitly confirm at Start. It is unchecked on reopen.
Keep the workstation awake; neither completion by morning nor recovery from every
backend failure is guaranteed. This does not change the operating-system sleep policy.

The versioned `bounded-pilot-provisional-v1` policy is recorded in the hash-chained
study ledger before execution. It accepts the eligible balanced recommendation
after each completed stage, including ambiguous or search-boundary-limited
evidence, within the existing grid and iteration caps. It does not claim a robust
winner, approve anatomy, launch an atlas, or start the Validation Lab. Failed
candidates and missing eligibility stop the pilot.

## Optional outward search

Without the outward option an unattended pilot accepts a boundary winner, and the
opportunity to widen that stage is spent: a completed study can no longer be
extended, in the interface or on the command line. The optional
`bounded-pilot-outward-v1` policy instead keeps adding outward logarithmic
neighbours whenever the preferred candidate sits on a tested boundary, and stops
widening only once the winner is interior.

That loop needs a declared stopping point, because a comparison score that
systematically prefers the outermost candidate would otherwise widen forever into
values that no longer describe the specimen. The researcher therefore declares a
positive feasibility interval per parameter before the run. The interface proposes
intervals derived deterministically from the tested grid — the smallest and largest
value it already covers, widened by `DEFAULT_OUTWARD_SAFETY_FACTOR` — and displays
the exact numbers in the Start confirmation. They are recorded in the consent
ledger and inherited by every successor study.

When the declared limits are reached and the winner is still on the boundary, the
run records that stage's boundary candidate together with an explicit
`automatic_search_budget_exhausted` ledger event, and the stored selection reason
states that the value is not an enclosed optimum. Stopping mid-pilot would not add
evidence; a repeated boundary win is itself evidence about the comparison score
rather than a validated parameter, and the residuals and reconstructions still
decide.

Selections use the distinct `automatic_provisional_afk_v1` provenance mode. Each
retains the original assessment, confidence, sensitivity warnings, boundary status
and a reason. Existing visual decisions are retained in the consent ledger and
remain binding on AFK resume; no missing visual approval is synthesized. A new
explicit visual decision may supersede an earlier one. Original-detail review
and scientific confirmation remain separate.

Cancellation is checked between candidates and stages; the backend is asked to
stop safely. Completed stages are not rerun. Reopening requires another explicit
AFK confirmation to continue. The completed dialog gives a short AFK return
summary; JSON/HTML reports preserve all decisions and remain provisional.

Regression coverage uses synthetic controller/metric fixtures, including four-stage
completion, ambiguity, failure/ineligibility, visual rejection, cancellation/resume,
no duplicate completed-stage execution, GUI confirmation/default-off behavior, and
the outward route: widening only with declared limits, staying off without them,
strict limit validation, and the recorded exhaustion notice.
It is engineering evidence, not a new biological or overnight-runtime study.
