# v138 follow-up: state, file I/O and cancellation

The owner requested another search for errors and optimization opportunities.
The additional source review and fault tests identified and repaired these cases:

| Trigger | Previous behavior | Repair |
| --- | --- | --- |
| Optional measurement cache cannot publish or remove its temporary file | Cleanup could propagate a permission error and abort the otherwise valid analysis | Cache publication and cleanup failures both fall back to the measured result |
| Open a different mesh-resolution study or change its assigned run | The previous report action could still point to the old assessment | Clear the report binding; study identity/face-count cells are read-only |
| Cancel an assessment after the last run-verification callback | Geometry/PCA comparison and report publication could continue without another cancellation boundary | Check cancellation between comparisons/PC endpoints and before final verification/publication |
| Save a method plot or 3D snapshot to a slow destination | File encoding/writing ran on the Qt thread | Use a bounded background exporter, reject duplicate starts and restore controls on success/failure |
| Close an export view while a save is pending | A busy marker could outlive the view | Clear its owned activity on destruction; accepted file writing does not access deleted Qt widgets |
| An older result's media export finishes after loading another result | Its completion could replace the new result's status | Bind completion status to the originating media/result context |
| Show cap advice in the QC page at a small window size | A wrapped paragraph could become a narrow column in the footer | Put the advice above the footer at full width; check 850×650 and 1140×900 layouts |

The exporter marks actual work through the existing activity indicator, so the
recorder uses the waiting rate while saving. Mouse activity still does not choose
the rate. Saved source meshes, checkpoints, scores and original results remain
unchanged.

The focused follow-up run passes 30 cases, including simulated cache permission
errors, a gated slow exporter with a live Qt event loop, duplicate-start rejection,
view destruction, stale completion, late cancellation, current-camera exports and
method/source bindings. These cases supplement the earlier v138 checks.

## Remaining performance candidate

Long legacy pilot-verification paths were observed during broad regression
execution, including repeated retained-stage/qualification reconstruction, path
resolution and YAML parsing. These are already outside the GUI thread in the
current pilot. Operation-local reuse is a candidate for profiling, with fresh
source checks and stale-input rejection retained. No new timing/RSS improvement
or demonstrated cause of an owner-reported freeze is claimed for that path.

The tested source changes require a fresh Windows build. The earlier incomplete
build is superseded; installation still waits for an idle app and backend.

## Test and CI follow-up

The shared pilot wait helper imported Qt even when only its scientific fixtures
were needed, breaking collection in headless Python 3.11/3.13 jobs. Qt now imports
only inside the GUI wait function; a blocked-Qt subprocess verifies that boundary.
Linux UI CI now installs the Pulse library required by Qt Multimedia. Startup
tests allow the specific FFmpeg version INFO line while retaining a zero-exit
requirement and rejection of other unexpected stderr.

Test teardown now deletes closed, newly created test windows while QApplication
and its event loop still exist; appearance preferences are isolated per test.
A mixed Windows run had aborted, and previous CI assertions could pass before a
nonzero process exit. After the fixture repair, the scoped desktop/v138 run passes
375 cases, skips one expected environment branch and exits normally with code 0.
The nearby isolated legacy qualification case also passes, taking 110.36 s.
No complete mixed-suite pass or demonstrated cause of an owner freeze is claimed.

These completion changes affect tests/CI/docs only, preserving the verified
runtime57b6278 build. See [delivery status](V138_DELIVERY.md).
