# v137: responsive pilot review and continuous process video

The v137 rates below are historical. v144 changes human review and decisions
from 10× to 1× while retaining 1000× calculations/loading; see
[current recording policy](V144_REAL_TIME_REVIEW_RECORDING.md).

Reviewing a long pilot history repeatedly verified ancestors, result files and
integration receipts on the GUI thread. The pilot now prepares its presentation,
comparison inputs, review persistence and stage selections in background workers.
Worker completions retain their verified snapshots. Display-only selection
changes reuse the prepared assessment; a new action still verifies its evidence.
Lineage verification is shared only within a single read operation and discarded
afterwards. No persistent hash cache or weaker acceptance criterion is introduced.

Pending presentation disables dispatch until verification completes. Stale or
closed-window deliveries are discarded; closing waits for an atomic review save.
Retained provisional baselines keep their warning while the next stage is ready,
as well as while it awaits review.
Shape approval, time-grid stability and optimizer convergence remain separate.
The provisional finish explanation identifies the source optimizer limit and
states when a finer grid evaluated the saved field without a new optimization.

An opted-in recording now covers the complete project session: pilot attempts,
reviews, atlas iterations and the evolving live plot stay in one video. Internal
worker completions never export or restart recording. **Finish recording**, normal
application close, disabling recording or changing projects saves the MP4.
The recording button does not stop a scientific computation.

Calculation and blocking-load phases use **1000×** playback. Reviews and decisions
use **10×**. The application's owned workflow tasks determine the rate;
mouse movement, clicks, keyboard activity and minimization do not change it.
Opening an information or review window during calculation retains 1000×.
Opt-in persistence, application-owned window capture and exclusion of foreign
applications/audio remain in place.

A GUI heartbeat gap longer than two seconds marks an unresponsive interval.
After recovery, that interval is omitted from playback and retained in the local
timing companion; wall-clock session time still includes it. Responsive backend
waiting remains in the video at 1000×. Detection is retrospective: it cannot show
uncaptured UI motion or distinguish every cause of a blocked event loop. Encoder
backpressure remains a declared capture delay, rather than silently removed time.
Old videos and interrupted recording fragments remain unchanged and recoverable.
MP4 publication also retries a bounded transient Windows sharing lock outside
the GUI thread.

Verification includes real MP4 encoding/decoding and packet counts, a deliberate
GUI stall, responsive waiting, mouse/keyboard activity during a tracked task,
task completion, owned review windows, repeated pilot/atlas completions without
splitting, slow presentation/review saves, stale deliveries and fresh-action
tamper rejection. Synthetic UI probes do not run scientific jobs or grant QC.
Source, frozen product, installed product and distributed installer remain
separate states. Native scientific validation and independent first use remain
separate from software regression checks.
