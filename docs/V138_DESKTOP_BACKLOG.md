# v138 — desktop backlog and method views

Source implementation, 19 October 2026. Build, installation and independent
first use are separate checks. The current scientific runs are not replaced,
continued or reconfigured by this development work.

## Results and visualization

Completed shape-space selections appear inside Results & PCA. A method selector
and axis selectors display the original, verified scores. Reopening a result
collects its saved selections, including methods absent from the latest subset.
PCA, kernel PCA, tangent-distance PCoA, Isomap and diffusion maps retain their
method identities. The last three use PCo, Dim and DC labels rather than claiming
principal components. Kernel components are labelled kPC. A method needs three
saved coordinates to offer its interactive 3D view.

The viewer places reduced reconstruction glyphs at unchanged score coordinates.
It supports rotation, pan, zoom, picking, specimen selection, camera reset and
glyph size. One common physical size factor retains relative specimen sizes.
Display-only clustering and vertex mapping reduce the entire surface; the
scientific meshes are unchanged. Frames use the existing bounded background
renderer and global depth sorting. Geometry is reused across method changes
after fresh source checks; closing cancels obsolete preparation between meshes.

Step 7 adds the same PC1–PC3 mesh morphospace for its prepared PCA media. Its
inventoried geometry remains outside the sharing-gallery ZIP allowlist. Individual
exports offer PNG/JPEG plots and snapshots, existing PNG/PDF figure plates, MP4
movies and the existing gallery ZIP. Exports verify source bytes and use atomic
publication; they cannot overwrite the saved run or media cache. A pending camera
view cannot be exported as if its old rendered frame were current.

This display feature does not refit an atlas, alter PCA, invent a third axis or
provide a native momentum preimage for nonlinear embeddings. The existing native
PC deformation calculation remains a separate operation.

## Continuation advice and desktop operations

At an eligible iteration cap, a background reader reports recent objective gains
over declared 10/50-iteration windows. It shows the observed sample counts,
absolute gain and relative change divided by the first objective's absolute
value. Printed precision bounds distinguish observed improvement from rounding.
The slowing heuristic compares the last 10-iteration rate with the preceding
part of the 50-iteration window. It reports flattening only when the recent upper
rounding bound is below one quarter of the earlier lower bound, and names that
cutoff explicitly. Rounded equal values, sparse observations, reset boundaries or non-monotonic
history do not establish a plateau. Advice is an explained heuristic; +300
remains an explicit, checkpoint-bound successor action.

New WSL runs supervise the unchanged native command inside an owned Linux
session. Launch-bound cancellation receipts identify that session and acknowledge
delivery, bounded escalation and the absence of active session members. A failed
or missing acknowledgement leaves the lifecycle nonterminal for explicit
stopped-process recovery. Logging callbacks cannot bypass this handshake.
Process-only checks are not a full scientific GPU cancellation qualification.

Saved-state final-export recovery is accessible from the desktop and uses the
existing unchanged-checkpoint export adapter through the supervised worker. The
source is retained, storage is checked and the user explicitly starts the new
export-only successor. It adds no optimizer iterations.

A completed or provisionally completed pilot can be reopened for targeted
refinement. A linked successor preserves the original final selection and history;
new fit evidence needs its own QC and applicable numerical checks. Fixed-state
resolution-adopted pilots retain their learned source and evaluated time grid.

Active parameter inputs are bound separately from a loaded result. Changing the
cohort, template, project, units, pattern, landmarks or alignment context prevents
reuse of the former project's pilot. Both pages show their own project identity.

## Appearance and concise guidance

Appearance settings provide light/dark themes, an arbitrary RGB accent, preview,
Save/Cancel and reset. Preferences persist; owned dialogs follow the theme.
Text and focus colors are adjusted for contrast, including pale/black accents.
Scientific figure colors remain independent of the interface accent.

The [26-location UI audit](UI_TEXT_AUDIT_2026-10-19.md) is addressed in the default
layouts and supporting help: one live counter, collapsed event history and
provenance, compact GPA diagnostics, one current review badge, shorter control and
method descriptions, and shorter completion/readiness/export messages. Parameter
controls keep a separate detailed reference. Numerical stop distinctions,
original-detail QC requirements, units and actionable errors remain visible.
Source/offscreen checks do not establish independent first-use acceptance.

The demo button, CLI mode, source, packaged assets and installer shortcut are
removed. An upgrade removes the old demo shortcut. Public scientific examples
and engineering fixtures remain.

## Preparation and research tools

Scalar mesh measurements are cached by source hash, measurement/software version,
sampling settings and the exact approved transform. Every reuse freshly hashes
the source; corruption and changed geometry/transforms invalidate it. Progress
and cancellation are supported between mesh checks. Existing project-preflight
and approved-transform reuse remain in place.

In a synthetic three-mesh test with one million triangles per mesh, measurement
time was 16.515 s cold and 0.194 s warm, with identical recommendations. This is
a measurement-cache observation, not an end-to-end pilot or private-cohort speedup.

The new [scientific mesh-resolution study](MESH_RESOLUTION_STUDY.md) freezes
researcher-approved scientific levels, derivation provenance and explicit
stability thresholds before runs. Separate generated configurations bind future
runs to that design. It compares atlas geometry, paired residuals, tangent
distances, PCA scores/subspaces and native reconstructed PC extremes. Missing
evidence blocks a face-count recommendation. It never simplifies inputs or
launches optimization automatically.

## Older roadmap reconciliation

| Work | Source status / remaining evidence |
| --- | --- |
| Cap improvement advice, themes, 3D morphospace and individual exports | Implemented here; delivery checks recorded separately |
| Demo removal | Source and installer entry points removed; installed inspection follows safe installation |
| Cancellation | Session supervision, acknowledgement and failure cases implemented; native scientific/platform qualification remains separate |
| Preparation performance | Scalar cache plus existing preflight/transform reuse; synthetic cold/warm checks; prospective end-to-end timing/RSS calibration remains open |
| Completed-result reopening | Existing operation-local verification and streamed QC retained; broader prospective reopening/RSS observations remain open |
| Completed-pilot refinement and desktop export recovery | Implemented here; original evidence/QC preserved |
| Active input/result distinction | Explicit identities and input-bound pilot reuse implemented here |
| Busy feedback and minimization | Existing ActivityPool and modeless window/minimize behavior retained; obsolete parentless-dialog test corrected |
| Reference PC deformations | Existing native physical-endpoint route retained; method-specific displays added here |
| Biological strata/extremes and bounded adaptive search | Existing selection/declaration and boundary-extension code retained; independent fit-quality/coverage qualification remains open |
| Mesh-resolution sensitivity | Prospective workflow and report implemented here; actual researcher-approved study observations remain open |
| Shared-core graphical application | Existing workflow/worker core retained; external usability acceptance remains open |
| Native Linux/macOS, signed distributions, NVIDIA qualification, HPC/Apptainer | No target test systems are available; platform/cluster execution and distribution claims remain open |
| Scientific release, benchmarks, biology, external testing, DOI/manuscript | External scientific/release gates; not software-test approvals or implicit publication authorization |

The owner confirmed that no additional native Linux/macOS or HPC test systems are
available. These gates have no invented pass, date or delivery claim. No cluster
job, installer distribution, release, scientific approval or private data upload
is implied by this version.

## Local engineering verification

The final focused run passes 94 cases; three environment-specific cases are
skipped (two Linux-only process tests and a missing-Qt branch on this Qt-equipped
Windows host). Thirteen unrelated main-window cases were deselected. Tests cover
saved score identity, all nine method labels, topology and cache reuse, stale
camera rejection, PNG/JPEG decoding, theme persistence/contrast, measurement
invalidation/cancellation, completed-pilot lineage, export-only dispatch and
supervised shutdown acknowledgement failures. Separate worker/protocol/advice
checks pass 44 cases. Ruff and the added-line whitespace check pass.

Source offscreen UI probes verify both appearance modes, an owned dialog,
method switching, unchanged 3D coordinates, current-camera export and truthful
export-only activity. They open no owner project and start no scientific job.
A process-only WSL test escalates an interrupt-ignoring child to SIGTERM and
acknowledges shutdown in 10.278 s; a mismatched token is rejected. An unrelated
process stays alive and the synthetic checkpoint stays unchanged in both cases.
These checks do not qualify native scientific GPU cancellation, anatomy or an
external operating system. Frozen delivery is recorded separately.
