# v131 — relative pilot feedback and a persistent best starting point

An anatomically inadequate fit can still improve on an earlier attempt. The
individual pilot now offers **Compare fits · better / worse** with a saved-fit
selector and synchronized side-by-side target/reconstruction views. Both views
use the same camera and scale. Preview geometry is cached; optional original
detail loads in the background. Feedback stays disabled while the selected
comparison is loading or navigating. Closing discards no scientific result and
late preview deliveries cannot apply a decision.

Choose **Better, still not right**, **Worse**, or **About the same**. The first
relative decision establishes a provisional best starting point; a better fit
replaces it, while worse or equal feedback retains it. The first-ever attempt
can be kept with **Improve from this fit**. Existing saved sequences remain
readable: an older good attempt can be selected when establishing the starting
point. Once a best exists, other history remains viewable, but direction feedback
requires comparison against that best, so improving on a poor recent trial
cannot silently displace a better older result.

The best is stored per specimen, bound to its immutable study/run identity and
deformation basis, and persists across reopening. Relative decisions have a
chained history and are stored before preparing a successor. A failed preparation
therefore preserves the chosen best. Stale comparisons, other specimens/series,
changed evidence and invalid fields cannot silently supply a different seed.

Subsequent individual attempts initialize from that best's verified momenta,
including ordinary improvement/rejection actions and longer-fit continuation.
A bounded set of twelve nearby attachment-width/noise-weight variations explores
around the chosen result while retaining its template, controls and deformation
kernel. Each successor is a separate optimization with fresh stopping history;
this is not an uninterrupted optimizer trajectory. Exhaustion requests an
explicit continuation or denser-model experiment. A new control basis starts a
separate sequence and needs fresh QC; old fields/approvals are not transplanted.

Relative ranking is not anatomical approval. It neither advances to another
specimen nor releases joint fitting, a final atlas or PCA. Existing explicit
specimen and joint-review gates, native equations, tolerance, original meshes,
saved results and approval records remain intact. A preferred initialization
does not guarantee a better next fit or establish biological correspondence.

Build/installation and independent first use are separate from source tests.
This feature does not implement the separately recorded demo-removal task.

## Separate-window recording repair

The normal saved-pilot open path previously created its modeless dialog without
an owning main window. The application-only recorder consequently excluded the
pilot and its nested review windows, and could not observe its computation-finish
signals. The pilot now has an explicit owner. Recording keeps the last visible
owned workflow window when another application takes focus, while still excluding
foreign windows. The video footer names the captured window.

Before a project config exists, the selected existing project directory now
provides the landmark recording destination. This avoids hiding the early
landmark session in application staging while later clips appear under the
project. Previously completed videos and scientific evidence are preserved;
missing pilot frames cannot be reconstructed as a live recording. Tests must
cover the actual saved-pilot constructor and real landmark/pilot/review windows,
not only a generic parented dialog. This repair does not record the desktop,
other applications or audio, and adds no scientific replay.

## Verification

The source checks cover 73 distinct regression cases across sequential and
progressive fitting, relative feedback, comparison rendering, recording and
version contracts. Three real native public-fixture fits checked exact reuse of
the retained best field after simulated worse feedback, without transferring QC.
An actual-window recording probe covered LandmarkEditorDialog, the normal saved
pilot opening path, its candidate viewer and the new preference dialog. Its
1080p MP4 decoded successfully with 42 distinct frames and zero reported capture
gaps. Foreign focus and early project placement were checked. These bounded
engineering observations do not qualify a long real-study session or establish
anatomical suitability; frozen/installed verification remains a separate step.
