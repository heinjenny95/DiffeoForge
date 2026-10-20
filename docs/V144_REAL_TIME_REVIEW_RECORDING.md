# v144: real-time fit-review recording

Owner feedback, 20 October 2026: the pilot review video was too fast to follow.
The former review/decision rate of 10× becomes **1×**. Calculation and loading
remain **1000×**. Tooltip, status, video overlay and new timing companions use
the same rates.

The existing workflow-task policy is retained: an active calculation or pending
review-mesh load remains accelerated; a ready fit awaiting human inspection is
recorded in real time. Mouse movement, clicks and focus changes do not select
the rate. The video remains one continuous opted-in project session, with the
existing bounded background encoder, declared capture delays and retrospective
omission of unresponsive GUI intervals.

Existing completed videos are not rewritten. Recovery of sealed older fragments
retains their original frames and recorded 10× timing rather than applying the
new recording policy retrospectively.

Verification covers decoded MP4 duration across review/calculation/review
transitions, real-time GUI capture after a loading phase, unchanged fast waiting,
GUI-stall omission, lock/corruption handling and recovery of legacy fragments.
These are presentation tests with synthetic fixtures; no private pilot/atlas fit
or scientific approval is part of this change. Frozen and installed verification
and independent owner acceptance remain separate delivery gates.
