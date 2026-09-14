# Background renderer lifetime repair

## Reproduced failure

At `fed80c744679e95b0e569f3f07eeb185723a3f9f`, repeatedly running only the five
surface-rendering tests reproduced a Windows native access violation
(`0xC0000005`, exit -1073741819) after 36 successful cases. The next case was
`test_identical_frame_is_cached_and_cancelled_scene_never_presents`. No atlas,
large mesh, Deformetrica process or execution-command reader was involved.
Local runtime: Windows, Python 3.12.14, PySide6 6.11.1, pytest 9.1.1.

Two diagnostic-only controls each passed 200 cases: retaining signal objects,
and retaining workers with runnable auto-deletion disabled. Neither unbounded
retention nor disabled deletion is used in the repair. These observations point
to the render completion/object-lifetime boundary; without a native debugger
stack they do not establish a particular Qt/PySide defect or prove that the
earlier Intel-Mac segmentation fault had exactly the same cause.

## Repair

Workers no longer own or emit through a GUI-affine signal QObject. They rasterize
their own QImage and put a result into a Python `SimpleQueue`. A cache-owned
10 ms QTimer consumes the result in the GUI thread, stops when idle, and launches
at most the latest pending view. Deleting the cache cancels its current render
through a Python-only callback; no worker accesses a destroyed QWidget/QObject.
Cancelled completions are rejected even when a cleared view reuses the same key.

This follows Qt's [QObject thread-affinity and lifetime constraints](https://doc.qt.io/qt-6/threads-qobject.html).
The thread pool retains its normal [QRunnable auto-deletion](https://doc.qt.io/qt-6/qrunnable.html).
No global object-retention list, renderer retry loop, synchronous GUI rendering,
test suppression, mesh decimation or numerical/analysis changes are introduced.

## Verification

- The original five cases passed 40 repetitions (200 cases) after the handoff repair.
- Nine expanded cases passed 20 repetitions (180 cases), including 2,000 explicit
  render-completion/owner-destruction cycles in the lifetime stress test.
- Added checks cover GUI-thread result delivery, idle timer shutdown, destruction
  during a blocked render, cancellation of a pending camera request and stale
  completed-image rejection after clear/key reuse. Existing full-face/full-edge,
  bounded navigation, caching and failure/no-repaint-retry checks remain intact.
- Complete local before/after suites and four-platform hosted GUI verification
  are pending. A passing stress run is bounded evidence, not a guarantee that all
  native GUI crashes or all real-data workflows are resolved. No installer changed.

Repetition recipe, run in a fresh process from the source checkout (diagnostic only):

```python
import pytest

class Repeat:
    def pytest_collection_modifyitems(self, items):
        items[:] = items * 20

raise SystemExit(pytest.main(
    ["-vv", "tests/test_desktop_surface_rendering.py"], plugins=[Repeat()]
))
```

The native-crash trace and control logs remain in the local task artifacts under
`artifacts/desktop_crash_20260914`; they are not research data or a runtime cache.
