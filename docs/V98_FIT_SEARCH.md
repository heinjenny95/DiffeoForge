# v98 — bounded fit search with specimen checkpoints

The guided first-stage **Find fit** action preserves the existing pilot and starts
an independent sequence of its original selected specimens. It runs one short
40-iteration attempt for the first specimen, then pauses for visual review.
The selected specimen farthest from the recorded representative shape is first;
this uses the existing pilot descriptors, not a new private analysis.

**Reject → next parameters** immediately starts the next attempt for that same
specimen. **Approve → next specimen** starts only the next specimen (120
iterations), then pauses again. Closing the viewer without a decision starts
nothing. Decisions are persisted before dispatch; stale viewers cannot advance
a newer checkpoint. No
approval is inferred from distance, speed or convergence. A failed/rejected fit
does not advance to another animal. **Try longer** recomputes only the current specimen with more
iterations and unchanged settings, starting from zero; it is explicitly distinct
from the existing multi-specimen warm continuation. Old attempts are retained.
The first specimen explores four motion/detail alternatives one by one.
Its approval locks the deformation kernel, integration settings and fixed
template/control basis. Subsequent rejected attempts vary attachment width and
noise on a finite stencil from one-eighth to four times the recorded matching
width and one-eighth to the original noise. After the first four attempts the
first specimen also uses this matching stencil around the lowest measured-distance
valid attempt; that center is persisted rather than repeatedly recentered.
Matching weights may differ for individual initialization; the joint fit uses
the first approved specimen's common settings. Individual fits are not an atlas.
Changing the common deformation basis requires an explicit **New fit search**
from specimen 1, with a separate budget and all previous evidence retained.
Exhausted alternatives or time budget stop visibly without automatic resets.

Individual probes fix the original template and generated control positions.
The template keeps its full topology. Control grids cover its bounds with at most
200 points. Separately hash-bound scientific target copies have approximately
20,000 faces, using topology/normal/boundary preserving decimation; preparations
remaining above 30,000 faces fail explicitly. These are not display proxies.

Each result is measured against the original target with 2,048 deterministic
area-stratified samples per direction and unsigned MeshLab point-to-triangle
distance. Worst size-normalized p99, worst p95 and equal-specimen mean determine
the geometric order; specimen-wise tails cannot be hidden in a pooled average.
Sampling, spatial normalization and nearest-surface distance remain limitations,
not anatomical correspondence or an automatic acceptance threshold.

After the final individual approval, joint confirmation starts one new
200-iteration fit with all original pilot targets. Verified fields sharing the
same template, controls, deformation basis and exact subject order initialize
this joint run. The project's original template/control freeze settings are
restored (normally both are optimized). Independent fields are initialization
only; they are not scientific PCA/PGA results. Joint outputs are newly computed.
Individual approvals are not carried into joint QC. The joint fit needs its own
convergence evidence and visual approval of all specimens before later stages.

Default total execution budget is 60 minutes, explicitly selectable from 15–240.
Preparation and computation consume the persistent shared budget; time waiting
for human review does not. The engine is cooperatively cancelled at the remaining
limit. Noninterruptible preparation, final measurements or verification may finish
after it. Closing/reopening cannot reset the budget or repeat completed runs.
Recorded pointers restore the current specimen without starting a calculation.
Old studies, individual decisions and unsuccessful attempts remain recoverable.

The legacy grid, later pilot stages and multi-specimen continuation remain
available. The bounded multi-specimen four-probe/refine/confirmation implementation
is retained internally and covered by regressions; guided UI now uses checkpoints.
Single-specimen field import is explicit and does not enable singleton PCA.

This changes feedback timing, geometry measurement and initialization. It does
not guarantee a usable fit, convergence or a global optimum. Very complex original
templates, scientific decimation, shared-template compromises and nonlinear minima
remain possible difficulties. No private fit/parameter-tuning run is performed
for development. Synthetic regression, packaging and prospective researcher
acceptance are separate evidence.

Verification: 29 focused sequence, search, dialog and build-version regressions
pass after the feedback change; earlier affected run-manifest, initialization,
PCA and startup regressions also pass. A tiny public synthetic singleton ran
successfully through the existing verified Deformetrica 4.3 runtime. Its fixed
control basis was checked at that runtime's six-decimal output precision. This
checks execution and file compatibility, not the quality of any private fit.
