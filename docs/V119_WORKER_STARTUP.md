# v119 Windows atlas-worker startup

An uncancelled reference worker could remain at **Reverifying reviewed
configuration and destination binding** before creating a run or starting
Deformetrica. A fresh-process trace located the main thread inside NumPy's
Windows extension loader while the command listener waited in a synchronous
stdin pipe read. Prequeued cancellation and preloaded numerical modules masked
the problem in previous engineering checks.

The shared worker pipe reader now uses `PeekNamedPipe` on Windows, briefly
waits when no bytes are available and reads only the available bytes. The
single-reader invariant prevents a competing consumer from draining those
bytes. Native functions and the descriptor handle are resolved before the
listener starts. POSIX retains `os.read`. Partial UTF-8, retained startup
commands, delayed cancellation and parent EOF retain their previous semantics.
The reference and Modern workers use the same transport implementation.

New fresh-process regression checks keep stdin open while loading NumPy and
then send a delayed UTF-8 command. Actual reference-worker subprocess tests
exercise exact-hash configuration verification and real preflight. Deliberately
wrong output binding or absent inputs guarantee terminal failure before any
preparation or engine execution. Frozen build verification now exercises both
uncancelled routes in addition to the existing queued-cancellation check.

The targeted Windows regression group passed 77 tests, including reference and
Modern worker/controller lifecycle tests, strict event transport and pilot-field
handoff regressions. Focused Ruff and diff checks passed. Frozen build and local
installation are independently verified before delivery is recorded.

The fix changes transport only. Parameter values, atlas initialization,
optimizer thresholds, checkpoint rules, integrity verification and human QC
decisions are unchanged. Existing scientific runs are preserved. Passing startup
checks does not establish anatomy, convergence or biological validity, and no
owner scientific run is started by development or installation.
