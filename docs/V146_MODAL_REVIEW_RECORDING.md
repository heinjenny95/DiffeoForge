# v146: record the real modal pilot review

Owner first use identified the missing case in v144/v145 recording checks: the
normal asynchronous comparison preparation opens the pilot fit viewer directly
from the loader's result callback. Earlier probes opened the viewer separately.
Their passing rate/duration checks did not cover that production transition.

`PreviewMeshLoader` previously published its idle state after delivering results.
The result handler enters the viewer's modal event loop, so the idle signal was
delayed until the viewer closed. The recorder selected the correct owned window
but still saw an active preparation task. It retained 1000× calculation timing,
leaving at most sparse review stills rather than the intended inspection footage.

The loader now starts any pending latest request and publishes the resulting
activity state before delivering success or failure. Completed preparation is
idle while its modal viewer is open; genuine pending/new work remains busy.
Stale and cancelled result suppression is preserved. The requested rates remain
10× normal interaction, 2× ready pilot fit review and 1000× actual busy/loading.
Existing videos cannot regain frames that were never captured and are unchanged.

Three new regressions fail on the former implementation: success/error callbacks
observe stale busy state inside a real modal loop, and the actual pilot open
path records a ready mesh viewer as waiting. After the fix, all 56 focused activity,
loader/proxy, recording and saved-pilot responsiveness cases pass. The integration
test uses the actual asynchronous pilot opener, rotates synthetic meshes inside
the actual modal viewer and decodes the MP4 to verify visible mesh frames, without
forcing review captures. It closes without recording an anatomy decision.

Frozen and installed verification exercise this callback/modal path and inspect
encoded mesh content, separately from timing; both pass. See
[verified delivery](V146_DELIVERY.md). Independent owner acceptance remains open;
synthetic presentation checks do not start owner scientific runs.
