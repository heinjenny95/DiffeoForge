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
- The final ten cases passed 20 repetitions (200 cases, 59.69 s), again including
  2,000 completion/destruction cycles. Destruction during an active render is
  tested both with and without an already-cancelling pending camera request.
- Added checks cover GUI-thread result delivery, idle timer shutdown, destruction
  during a blocked render, cancellation of a pending camera request and stale
  completed-image rejection after clear/key reuse. Existing full-face/full-edge,
  bounded navigation, caching and failure/no-repaint-retry checks remain intact.
- A fresh complete baseline run passed 1,597 tests with seven skips (752.48 s),
  despite the separate renderer-only crash: the failure is intermittent.
  The repaired complete local suite passed 1,601 tests with seven skips (777.08 s).
  This full run collected the nine-case version; the final additional parameter
  case is covered by the final ten-case repeat above. Skips concern the installed
  PySide6 condition and this Windows account's symbolic-link permissions.
- [CI 34839397593](https://github.com/heinjenny95/DiffeoForge/actions/runs/34839397593)
  at implementation commit `6e5eb99bc1f2662a2532f01a0114a8814df8f20e` passed all ten
  jobs: 1,485 tests on each host Python version; desktop Windows 203 passed / 14
  skipped, Linux and both Apple-Silicon/Intel Mac 196 passed / 21 skipped each;
  all three Modern engine jobs and the synthetic CPU agreement gate passed.
  [Reference CI 34839397585](https://github.com/heinjenny95/DiffeoForge/actions/runs/34839397585)
  also passed both standard container runners. No numerical policy changed here.
- These are bounded observations, not a guarantee that all native GUI crashes or
  all real-data workflows are resolved. In particular, a later green Intel-Mac
  run does not prove the cause of its historical segmentation fault. No installer
  changed during that code-verification stage; the later authorized same-owner
  build/install and subsequent interactive observations are recorded below.

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

## Same-owner Windows installation observation

On 14 September 2026 the user authorized building, installing and smoke-testing
the repaired desktop. The private unsigned build is pinned to
`063143a8cf7c94206d1f85b034455fedf726da4d`; no binary was uploaded or released.

- The full frozen-process contract passed, including the 21-event synthetic
  Modern run, reference cancellation/parent-death audits and approval-bound
  preparation without reference-engine execution. Dependency metadata and the
  CycloneDX evidence verified (27 packages).
- All eight Python modules and both schema files changed since the previously
  installed `8670974e3af1232d5e9c4f0cb3959068f8e9be62` were independently compared
  inside the frozen bundle against committed source. Embedded code-object
  comparison normalizes only source filenames, not instructions or constants.
- The 2,676-file bundle contains 764,628,899 bytes. Every installed bundle file
  was hash-verified; the installed startup `--smoke` exited 0 and the Desktop
  shortcut targets that installed executable. The installer exited 0 without
  a restart. All 2,687 files of the previous installation were moved to the
  existing local backup folder and hash-verified. Study data, checkpoints and
  the separate reference runtime were not changed.
- Interactive viewer manipulation was **not verified on 14 September**: the Windows
  computer-use service rejected both launch attempts with `GetCursorPos`
  access denied (`0x80070005`). This is a desktop-access limitation, not an
  observed DiffeoForge crash. Rotation and close/reopen checks were deferred until
  desktop access returned; the offscreen startup test was not a substitute.

Exact SHA-256 identities:

- Installed EXE: `a81c1db7f1b3ff378f0cf9fdfffdbb8611b9cd98644ffee76170e072d64f3f64`
- Setup: `da61fcaa4dd358a657755359d5a313fb94c912ce4167cceeda658334315cd9f3`
- Freeze evidence: `c62ac4721ce9b5228ce245315ed4815370384bbe89f469ac17fb66f8563b9914`

Local build/install receipts remain under `artifacts/renderer_install_20260914`.
This same-owner installation does not establish public redistribution approval,
code signing, clean-machine support, real-cohort performance or biological validity.

## Interactive installed-viewer observation

On 15 September 2026 Windows desktop access was available again. The same installed
EXE hash above was rechecked, and the following bounded checks ran through its
normal visible UI, not an offscreen test harness. No rebuild or reinstall occurred.
Inputs were six public synthetic VTK ellipsoids (162 vertices / 320 triangles each)
and three corresponding landmarks per mesh, not private research specimens.

- Landmark editor: the template rendered; drag rotation visibly changed its
  orientation; Next mesh loaded `subject-01.vtk`; the Front preset changed the
  view. Cancel and reopen restored a fresh template render. The point count stayed
  at zero and the dialog reported that no landmark draft had been written.
- Read-only GPA preview: six meshes / three landmarks converged in four iterations.
  The GPA viewer rendered the cohort overlay and followed drag rotation. Enabling
  the selected shaded surface, selecting Highest residual (`subject-04.vtk`),
  hiding the overlay and wheel zoom all produced updated visible frames. Closing
  without completing review and reopening restored the template overlay.
- No app crash or visible freeze occurred during these checks. The app closed
  normally and relaunched with an empty new-project form. No alignment approval,
  project publication, atlas or Validation Lab execution was requested.
- Minor open UI issue: after hiding the cohort overlay, the in-canvas legend still
  says that all six meshes are shown. The actual view switches to the selected
  mesh; the label needs to reflect the display mode.

This checks two installed viewer families on small synthetic inputs. It is not a
large-mesh performance measurement, direct interactive coverage of every QC/PCA/
calibration viewer, or proof that every intermittent native crash is resolved.
The historical Intel-Mac crash still lacks an established native root cause.

### Large synthetic follow-up, same day

The next bounded installed landmark-editor check used 200k-face synthetic meshes:
the template displayed a labelled 5,224-face proxy, drag rotation changed its
orientation, Next mesh displayed the 5,069-face subject proxy, and explicit
Original detail rendered all 200,000 faces. Closing and reopening restored the
template proxy with Original detail unchecked. The point count remained zero,
no draft was written, and the test project path was never created. The app closed
normally. Its installed binary was not replaced.

Separately, nine offscreen production-canvas observations (three sizes across
three viewer families) completed 27 reopen cycles and nine explicit owner
destructions with rendering outstanding. The source-only GPA legend fix covers
all eight combinations of cohort, surface and landmark visibility. Measurements,
reproduction and remaining scope gaps are in
[desktop-viewer-matrix-v1](../reference/desktop-viewer-matrix-v1/README.md).
