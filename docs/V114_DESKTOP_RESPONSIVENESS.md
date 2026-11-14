# v114 — keep template preview and saved-pilot checks responsive

Loading the native template preview already used a background mesh worker.
However, refreshing its controls synchronously reverified the saved pilot several
times on the GUI thread. Saved-sequence resolution could also verify earlier
individual fits. In a read-only local measurement, mesh preparation took about
2.7 seconds while one complete study verification took about 85 seconds.

Ordinary pilot status and button updates now use a background verifier and a
cached status snapshot. Project identity and record timestamps invalidate this
UI cache. Repeated refreshes do not enqueue duplicate checks; errors remain
visible, changed records trigger another check, and old-project responses are
discarded. The activity indicator distinguishes checking a saved pilot from
loading a template. Template loading has short immediate feedback.

Explicit pilot opening separately resolves and strictly verifies current evidence
in a background worker. A completed pilot is applied only after this fresh check;
the status cache never authorizes a scientific action. An incomplete pilot passes
the freshly verified snapshot to its dialog, avoiding two further synchronous
loads. Closing the dialog uses its latest verified snapshot. A requested close or
project change prevents a late open from applying parameters or opening a dialog.

No pilot outputs, parameters, optimizer criteria, anatomical decisions, scientific
geometry or numerical thresholds change. This update starts no scientific run.
The explicit-open verification still takes time for a large saved study; it now
reports activity without blocking the GUI. This is not the separate completed-
pilot refinement feature or a guarantee that every viewer operation is fast.

## Verification

Eighty-one scoped regressions passed; one optional-dependency test was skipped
because Qt is installed. Ruff and diff checks passed. Coverage includes a held
background verifier with an active GUI timer, repeated status queries, record
invalidation and cached failure, old-project response rejection, fresh rejection
of tampered evidence despite cached status, safe late-open/close behavior,
completed-pilot application and dialog snapshot reuse. The existing generic-copy
test now allows the dataset-independent term "joint fit".

A separate offscreen main-window harness loaded the unchanged owner template and
saved configuration read-only: preview readiness was about 2.8 seconds, enqueue
time about 1 millisecond, and ordinary control refreshes at most 24 milliseconds.
The GUI timer continued and no complete study loads occurred during the preview.
Protected configuration, alignment and pilot journal hashes stayed unchanged.
These local measurements are not a portable performance promise. Native owner
interaction, broader viewer performance and scientific acceptance remain open.
Packaging and installation evidence are tracked separately.
