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
