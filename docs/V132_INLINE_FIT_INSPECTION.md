# v132 — compare and decide in one fit inspection

Individual-fit inspection now presents the saved previous/best fit beside the
current reconstruction, with a shared camera and scale. Its fixed decision
footer has two explicit steps:

1. Choose **Better**, **Worse** or **About the same**.
2. **Accept** the current anatomy or **Reject** it and try the next attempt.

The separate, collapsed comparison entry point is removed. Selecting a relative
rating keeps the inspection open and neither writes a decision nor launches a
fit. Both final buttons stay disabled until a valid relative choice and the
displayed comparison are ready. Changing the compared fit invalidates that
choice. The first fit has an explicit starting-point choice because there is no
previous attempt. An already selected best can retain its existing starting
point. Technically invalid fits remain rejectable but cannot be approved or
promoted as initialization.

The current inspection canvas and loaded mesh objects are reused. Selecting a
different saved fit loads only its reconstruction; optional original detail
uses the existing loader. The comparison/rating and final controls stay in the
same owned workflow window and remain visible at the minimum supported size.
Joint/all-specimen review retains its existing review gates.

Only the final explicit accept/reject callback persists relative preference,
then records the existing anatomical review and requests its ordinary next
step. Better promotes the current fit; worse/equal retains the best. Rejected
improvements can therefore guide a successor without becoming approved anatomy.
Closing without a final decision records neither preference nor QC. A stale
current/reference/best identity cannot silently supply another starting field.

Relative preference is saved before subsequent QC/preparation. If a later step
fails, the saved best survives, no automatic recovery is started, and the owner
reopens the inspection to continue. Each successor remains a separate native
optimization. Scientific equations, stopping rules, original geometry and
approval boundaries are unchanged.

Source, tested build, installed runtime and installer distribution remain
separate states. Long real-study recording and independent first-use acceptance
are separate from bounded engineering checks. Demo removal remains open backlog.

## Source verification

87 distinct regression cases passed; the final UI/recorder subset also passed
all 27 cases after layout refinement. An actual pilot-callback probe with real
native public-fixture fits verified ranking before QC, no write/dispatch on the
relative choice, shared camera/scale, reuse of the current mesh objects and a
native successor initialized from the retained best after final rejection.
Minimum-size layouts were visually inspected. The actual-window recording probe
decoded a 1080p MP4 with 36 distinct frames and no reported capture gaps, covering
landmarking, pilot and integrated fit inspection/rating. These bounded source
observations do not establish long-session behavior; frozen/installed checks are
tracked separately. Those exact-product frozen and installed checks have now
passed, and tested v132 is installed; see [delivery](V132_DELIVERY.md).
