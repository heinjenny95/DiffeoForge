# Bounded AFK / overnight pilot

AFK is an opt-in alternative to the standard robustness-gated automatic pilot.
Check the AFK option and explicitly confirm at Start. It is unchecked on reopen.
Keep the workstation awake; neither completion by morning nor recovery from every
backend failure is guaranteed. This does not change the operating-system sleep policy.

The versioned `bounded-pilot-provisional-v1` policy is recorded in the hash-chained
study ledger before execution. It accepts the eligible balanced recommendation
after each completed stage, including ambiguous or search-boundary-limited
evidence, within the existing grid and iteration caps. AFK does not create outward
search extensions even when standard mode has separately declared extension limits.
It does not claim a robust winner, approve anatomy, launch an atlas, or start the
Validation Lab. Failed candidates and missing eligibility stop the pilot.

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
no duplicate completed-stage execution, and GUI confirmation/default-off behavior.
It is engineering evidence, not a new biological or overnight-runtime study.
