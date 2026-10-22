# v154 internal delivery — pilot feedback and earlier-fit recovery

Source implements [relative feedback and recoverable refinement](V154_PILOT_FEEDBACK.md).
Source checks and a complete synthetic workflow probe pass with native dispatch
guarded. Exact frozen/installed runtime checks and installation are pending at
this source snapshot; completion will be recorded separately after verification.
No owner/native fit, public release, tag or installer upload is authorized here.

Two pre-existing responsiveness-suite assertions still fail when they require a
particular downstream loader callback count. Fresh evidence is rejected earlier
by the background guard. The same two failures reproduce on the unchanged v153
baseline, as previously documented for v148. They are disclosed separately from
the passing feedback and workflow tests; neither failure establishes a new
responsiveness or stale-evidence regression.
