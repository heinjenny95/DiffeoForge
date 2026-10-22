# Next DiffeoForge development version

Owner scope, 22 October 2026: the owner subsequently authorized implementing all
recently collected pilot follow-ups. v150 addresses their software changes below;
scientific fits remain excluded. See [scope and verification](V150_PILOT_REPAIRS.md)
and [verified dev150 installation](V150_DELIVERY.md).

## v149 — owner-authorized guided pilot, 21 October 2026

Template suggestions, adaptive diversity-based pilot size, one-target method
comparison, explicit tie/unfit/uncertain decisions, optional saved comparisons and
joint-model retention are implemented and installed as dev149. See [v149 scope
and limits](V149_GUIDED_PILOT.md) and [verified delivery](V149_DELIVERY.md).
Source/exact frozen/installed workflow and review-video checks pass; prospective
scientific and selector validation remains open. No new scientific fits started.

## v147 owner-authorized automatic matching comparison — 21 October 2026

New guided pilots compare Current and Varifold with matched fresh trials and
common geometry measurements before further calibration. Provide a concise
recommendation only for a stable advantage without subject/regional regressions;
keep inconclusive results for visual selection. Preserve existing pilots and
one method throughout subsequent stages/full-cohort preparation. Implementation
and verification boundaries: [v147](V147_AUTOMATIC_ATTACHMENT.md).
The owner explicitly requested no new fits during implementation or delivery.

### Pilot method explanation — owner follow-up, 21 October 2026

- [x] Before the automatic comparison starts, visibly name **Current and
  Varifold** and briefly explain why both are tested: surface orientation can
  affect matching, and the pilot checks which representation follows the pilot
  surfaces better. Explain in plain language that Current uses surface direction
  while Varifold treats opposite directions alike. Do not require users to open
  technical help to discover what “both methods” means. Use one concise visible
  explanation without repeating it across status labels and the action button;
  keep further detail collapsible. Implemented for the new v149 guided route;
  historical studies keep their recorded protocol. Scientific first use remains open.

> v94 supersedes unattended stage advancement: each stage batches its candidates,
> then waits for recorded visual acceptance of every specimen. The former AFK
> controls and policies below describe historical behavior. Existing ledgers remain
> readable. See [current fit-first workflow](V94_SURFACE_FIT.md).

Scope agreed on 2026-09-14: implement the current usability backlog and plan the
larger roadmap. This is a development plan, not a public release or scientific
qualification claim. The established development branch remains authoritative.

## v138 owner-authorized implementation — 19 October 2026

The owner subsequently requested implementation of these items and the older
software backlog while the atlas continues. v138 source implements the items
below; [scope and older-task reconciliation](V138_DESKTOP_BACKLOG.md) separates
software delivery from native/platform, prospective scientific and user gates.
Installation waits for an idle application/backend. No additional Linux/macOS or
HPC test systems are available.

## Owner-requested backlog — 19 October 2026

- [ ] Prepare all configured PCA/method results and their visualization assets
  as part of final atlas export/postprocessing, **only after verified native
  convergence**. A finished workflow should expose the available mesh plots,
  interactive 3D data and supported media immediately, without starting their
  expensive preparation when a view is opened. Cap-only, cancelled, interrupted
  and failed runs must not trigger this automatically. Show progress and report
  unavailable/failed assets honestly; preserve human anatomical approval as a
  separate step. See [acceptance criteria](PCA_VISUALIZATION_EXPORTS.md#prepare-results-before-converged-atlas-completion--pending).
  Backlog only; not implemented in v138.

- [x] At an atlas iteration cap, summarize recent objective improvement and explain
  whether **Continue +300 iterations** appears worthwhile, the curve is flattening,
  or the history cannot support advice. Show recent-window gains and transparent
  comparison/precision limits; keep optimizer convergence, anatomy approval and
  manual continuation separate. See the
  [roadmap acceptance criteria](../ROADMAP.md#atlas-stopping-and-continuation).
  Implemented in v138 source with precision-aware 10/50-iteration windows.
  Existing runs and native stopping rules are unchanged.

- [x] Continue simplifying text throughout the interface, including dialogs and
  already-collapsible help. Show the relevant outcome and next action, shorten
  explanations, and replace repetitive/formulaic AI-sounding copy with natural,
  direct language. Move routine technical detail to background-written local
  logs that users can find and search; keep actionable errors, essential warnings
  and required decisions visible. Extend the existing
  [text-reduction task](../ROADMAP.md#milestone-3-accessible-application), with
  representative workflow/user review. v138 implements this source pass;
  longer-term usability review remains open.
  Concrete acceptance example: remove duplicate specimen/optimizer counters from
  the adjacent live-event status and cohort-initialization progress caption.
  Retain one compact summary, the phase and progress bar; keep history in logs.
  Use the [26-item source audit](UI_TEXT_AUDIT_2026-10-19.md) as the concrete
  checklist, covering main pages, pilot/QC, GPA/landmarking, comparisons,
  validation and visualization. The 26 source locations are revised in v138;
  independent first-use review remains open.

- [x] Add an interactive PC1–PC3 3D morphospace to Step 7 Visualization, using
  miniature meshes at the saved PCA coordinates, with rotate/pan/zoom, selection,
  glyph-size controls and responsive cached rendering. Add direct per-item
  image/video export throughout Visualization: PNG/JPEG stills, MP4 videos and
  a snapshot of the current 3D camera; preserve existing PDFs and gallery ZIP.
  See [detailed scope](PCA_VISUALIZATION_EXPORTS.md#deferred-follow-up--19-october-2026).
  Implemented in v138, extended to saved comparison methods with correct
  axis names. No atlas/PCA recomputation or active-run change is implied.

## Longer-term UI customization — low priority

- [x] Support light/dark modes and user-selected UI colors, including an arbitrary
  replacement for the current teal accent. Persist appearance preferences, apply
  them consistently across main and secondary windows, retain readable interaction
  states and provide a default-theme reset. See the
  [roadmap item](../ROADMAP.md#longer-term-ui-customization--low-priority).
  Implemented in v138 source with persistent preferences, owned-dialog
  theming, contrast adjustment, preview/cancel and reset.

## v129 owner-selected implementation

The follow-up v130 process recorder implements saved opt-in, active 10× / waiting
300× capture and automatic MP4 export after each computation, followed by a new
recording for QC and subsequent work. See [scope and limits](V130_PROCESS_RECORDING.md).
It records presentation only and never advances or recovers scientific work.

The owner authorized Pilot/PCA implementation on 18 October 2026, including an
in-app Visualization page and pilot-informed iteration-budget headroom. v129
supersedes the older explicit-click requirement for axis shapes: preparation is
automatic after verified result/QC release, with source-bound reuse and failure
handling. Scrollable pilot tools, content-bound mesh reuse, the native physical
endpoint repair and media-only export are implemented and installed after separate
frozen/installed engineering checks. Independent first-use acceptance remains
open. See [v129 scope](V129_PILOT_AND_VISUALIZATION.md) and
[verified delivery](V129_DELIVERY.md). Historical checklists below retain
their original context; unrelated research/platform gates remain open.

## Adaptive search implementation

v96 implements bounded feedback search and learned-state continuation in the
ordinary pilot. See [behavior, evidence and limits](V96_ADAPTIVE_PILOT.md).
Independent usability and prospective fit-quality acceptance remain open.
The earlier manual refinement proposal below is superseded by the direct
**Improve fit automatically** action; the other backlog items remain separate.

## Delivery order and acceptance gates

### Guide recovery after an unsuccessful contrasting-form check — open

Owner first-use feedback after v150, 22 October 2026: both methods fitted the
first form well; one was better on the second form. The pilot then used only
that method on a new form, whose fit was unsatisfactory. The user could continue
only by finding the collapsed targeted-options panel, identifying missing local
detail and requesting a denser follow-up. The ordinary guided route did not
make the next step clear. Tracking only at the owner's request; no implementation
or new fits authorized by this entry.

- [ ] After rejection of a contrasting-form fit, visibly explain that this
  configuration has not passed that form and present an obvious next action to
  improve it. Do not leave the user dependent on discovering collapsed tools.
  Ask a short visual question about what fails (local detail, overall shape or
  uncertainty) and recommend a bounded, targeted next comparison in plain
  language. Explain what the proposed change is intended to address; missing
  detail must not automatically imply that denser control points are the answer.
- [ ] Keep method preference conditional on the tested forms/settings. When a
  previously preferred method fails a new form, offer a suitable targeted change
  or a comparison with the other method on that difficult form, rather than
  treating the earlier choice as universally settled. Preserve earlier fits and
  reviews, reset dependent cross-check eligibility after parameter changes, and
  show the planned specimen/trial count before an explicit Run action. Do not
  silently approve, restart the whole pilot or launch a full-cohort grid.
- [ ] Verify the complete reported route: first pair both good, second pair one
  preferred, chosen-method check on another form rejected, then a visible guided
  recovery path (including local-detail and unsure responses). The user must be
  able to continue without knowing LDDMM terms or opening optional technical tools.

### Pilot layout clipping and unclear next action — v150 source

Owner feedback, 22 October 2026: the running pilot view shows an apparently
clipped control region (a narrow colored fragment) above extensive empty space.
The owner also reports that the required button for continuing was not green.
The screenshot contains ongoing iteration progress, not a displayed backend
failure; the layout cause and the preceding actionable-button state need
reproduction. The subsequent development request authorizes the v150 repair.

Additional completed-view evidence from the same owner session: selector rows
and duplicate Inspect fit buttons overlap, with another clipped control fragment.
Check whether controls from the previous view remain during refresh; the exact
cause and any candidate-binding effect are unverified. Extend this existing
layout issue rather than create a separate duplicate.

- [x] Diagnose and repair clipped/partly hidden pilot controls and inappropriate
  empty space. Verify layout after batch/state transitions, window resizing and
  relevant display scaling; labels and available actions must remain readable
  and reachable. Verify that previous-view controls are removed or replaced and
  current selectors/actions form one coherent, non-overlapping view. Check that
  Inspect fit opens the selected candidate and saved alternatives remain clearly
  distinguished from the current fit. Do not infer a failed scientific fit from
  this UI symptom.
- [x] Make the currently required, available next action consistently prominent
  with the established green primary style and a clear label. Do not highlight
  an unavailable Run/Continue button while a batch is already computing; show
  progress and the relevant safe cancellation instead. Verify both the ready
  state before clicking and the running state afterward, without auto-advancing
  or recording an approval.

### Pilot decisions appear before visual assessment is possible — v150 source

Owner feedback, 22 October 2026: while the method batch is still computing, the
overview already presents decision paths such as Both good / Both unfit. Showing
unavailable or premature decisions makes the required order unclear. The owner
initially requested tracking only, then authorized the v150 repair.

- [x] Reveal accept/reject controls only after the relevant original and
  reconstruction have actually rendered in a usable comparison. Hide premature
  actions instead of merely disabling them during loading or when no comparison
  can be displayed. Reveal aggregate decisions such as Both good / Both unfit
  only after the required fits are available and their individual visual reviews
  have been recorded. Keep relevant progress, error/retry, safe cancellation and
  close controls accessible. Readiness must follow displayed geometry rather
  than file existence or optimizer completion alone; never infer visual approval.
  Check computing, initial loading, render failure, specimen switching and the
  transition to a reviewable fit. No new fits are authorized by this entry.

### Initial-template recommendation misses local fit risks — v150 source

Owner first-use feedback, 22 October 2026: the v149 suggestion can return the
same kind of locally distinctive form that previously fitted poorly. Current
ranking uses coarse radial/spectral centrality; it does not establish deformation
suitability and does not consult previous fit reviews. The delivered heuristic
does not close this issue.

- [x] Improve and validate template suggestions using local shape differences
  at multiple scales as well as overall cohort coverage. Keep the method general
  across surface datasets; do not hard-code anatomy or prefer fewer protrusions.
  Where compatible previous fit/review evidence exists, present it with its
  source, target, method and settings context; a rejected fit must not become an
  unconditional template blacklist. Expose uncertainty and meaningfully different
  alternatives, preserve manual choice, and test local-detail sensitivity and
  mesh-sampling robustness before claiming a suitable starting template.

### Repeated cohort loading before pilot selection — v150 source

Owner feedback, 20 October 2026: preparing the pilot reads the whole cohort
again after earlier input/GPA steps. Full-cohort shape measurements support
representative pilot selection; repeated full geometry parsing across these
steps is the performance follow-up. The existing scalar measurement cache
does not establish reuse of geometry already loaded by another step.

Owner reaffirmed on 22 October after v149 first use: the repeated-loading problem
is still observed. Source inspection identifies a preparation path that builds
the alignment preview before checking for existing aligned outputs; without an
approved preview this can parse the entire source cohort again. The v149 scalar/
VTK-metadata cache is a partial improvement, not a completed fix for this path.

- [x] Profile and remove avoidable repeated mesh loading between input checks,
  GPA and pilot parameter analysis. Reuse verified geometry or aligned
  measurements with exact source/transform/settings binding and bounded memory.
  Check reusable saved alignment evidence before rebuilding geometry, including
  application reopening and non-VTK originals. Do not equate enumerating/checking
  every input with needing to parse every full mesh again.
  Keep fresh file hashes and stale-input rejection. Verify cold/warm transitions,
  reopening, cache invalidation and unchanged measurements/pilot selection;
  separate hash I/O from parsing/transformation costs. Show whether the app is
  checking files, reusing measurements or measuring shapes. Preserve full-cohort
  coverage for selection and the chosen subset for actual pilot fitting.

v150 checks saved alignment before preview construction, including reopening and
non-VTK sources, and streams cold-preview geometry one mesh at a time. Synthetic
parse/lifetime and invalidation checks qualify those repairs. v149 scalar caches
remain in use. Large-cohort wall-time/RSS and independent first-use gates remain
open; no universal speedup or skipped integrity I/O is claimed. Template ranking
remains provisional. See [limits and verification](V150_PILOT_REPAIRS.md).

### Priority: slow pilot previews and invisible QC locks

First-use feedback on 2026-09-28: preview loading is too slow and the specimen
decision/rejection controls appear inert. Static inspection found that both
depend on registered full-detail presentation, while preview loading still
parses full meshes and builds full edges. Existing display-proxy caching occurs
after full parsing. The actual runtime bottleneck has not yet been profiled.

- [ ] Put the specific lock reason and a direct **Load detail for QC** action
  beside decision controls; clearly style disabled controls, including rejection.
  Distinguish loading, preview ready, detail ready and failure with concise copy.
- [ ] Support early rejection/uncertainty based on a successfully displayed
  preview with explicit preview-only evidence scope. Keep these concerns separate
  from full-detail inspection and final acceptance; preserve every-specimen pass
  requirements and reject stale/unloaded specimen decisions.
- [ ] Measure cold/warm time to first useful image and specimen/option switches,
  separating I/O/hash, parse/inspection, edges, proxy generation and rendering.
  Choose a performance target from measurements rather than assuming a cause.
- [ ] Reuse verified previews and unchanged originals across comparisons; avoid
  full parsing/edge preparation on repeated preview loads. Evaluate bounded,
  content/version/resolution-bound project-local display caching and on-demand
  full detail without modifying scientific geometry or weakening source checks.
- [ ] Keep navigation/closing responsive, discard stale callbacks and bound
  cancellation/prefetch work. Show honest progress and actionable errors. Verify
  large-mesh cold/warm loads, review transitions and loading/rendering failures.

Backlog only; no performance result, runtime change or new QC approval is claimed.

### Planned: clear pilot review, refinement and continuation

Backlog recorded 2026-09-28 after first-use feedback; implementation is pending.

- [ ] Separate **Review selected option**, optional **Refine fit**, and using an
  approved option to continue. Use a neutral option chooser and visible QC status;
  the current "Choose an option to review or refine…" omits continuation.
- [ ] Once all specimens pass and approval is saved, emphasize a primary action
  such as **Use this option and continue to stage 2**, adapted to the actual next
  stage or final handoff. Keep re-review/refinement secondary. If blocked, show
  the specific remaining requirement briefly rather than only a disabled button.
- [ ] Explain refinement where it is offered: propose new parameter combinations
  around the selected fit; do not imply stage advancement or direct mesh repair.
  Distinguish preparing the comparison from starting calculations. Audit adjacent
  controls, including **Prepare next stage**, confirmation and Run labels together.
- [ ] Show the base option and new-option count before an explicit **Run new
  refinement options** action; make progress, completion, current stage/round and
  return to comparison clear. Distinguish retained results from new options and
  preserve valid saved reviews; new options require their own QC. Refinement is
  optional when the selected option already meets continuation requirements.
- [ ] First-use acceptance must cover review -> approve -> continue, failed or
  uncertain fit -> optional refinement -> run -> review, and returning to a
  previously approved option. Preserve the theme, concise copy, existing results
  and every-specimen approval gate; keep detailed explanations collapsed.

### Planned: discoverable axis shapes and precise method terminology

Backlog recorded 2026-09-28; no implementation or new numerical run is claimed.
The [reference analysis and PC Shooting route](REFERENCE_PCA.md) already exists.

- [ ] Place **Show shape changes along PC axes** beside the Results morphospace,
  with available PC1–PC3, mean-momenta and minus/plus 2-SD shapes. Reuse verified
  outputs; keep the existing theme and put technical detail in collapsed help.
  Distinguish observed specimen meshes at score positions from modeled axis
  shapes. Require an explicit click for missing outputs, visible progress and
  protection against duplicate work or console popups.
- [ ] Audit UI, figure/PDF/export and methods labels against each saved result's
  method. Describe the reference default as LDDMM-metric tangent-space PCA and
  explain its relation to linearized PGA. Preserve the identities of Cartesian
  PCA, Modern-engine analyses and generic RBF KernelPCA. Do not alter old scores
  or evidence merely to change terminology.
- [ ] Add concise methods text citing the applicable
  [Vaillant et al. (2004)](https://doi.org/10.1016/j.neuroimage.2004.07.023)
  tangent-momenta framework and
  [Fletcher et al. (2004)](https://doi.org/10.1109/TMI.2004.831793) PGA context.
  State the tangent approximation; claim neither exact nonlinear PGA nor an
  intrinsic mean solely from shooting mean momenta. Keep the main UI concise.
- [x] Statically compare the supplied reference helper with existing endpoint
  construction: both use mean plus a signed score times the already inverse-
  mapped momenta component, with SD steps scaled by sqrt(explained variance).
  The helper prepares momentum fields only; actual Shooting already exists here.
  No external code was executed, imported or published.
- [ ] Complete the endpoint audit and bounded numerical comparison. Check
  centering, mean +/- 2*sqrt(eigenvalue)
  times the inverse component, metric normalization/inverse mapping, component
  signs and XYZ/control-point order. Retain the fitted template, control points,
  deformation kernel and integration settings. Implement verified gaps only.
- [ ] Any reusable reconstruction helper must enforce the supported method and
  feature-space contract, label Cartesian and metric PCA separately, handle
  zero-variance modes and reject non-finite outputs. Retain source/control-point
  binding and immutable output publication rather than a parallel overwrite path.
- [ ] Verify momentum serialization against the exact source Deformetrica
  runtime, including header, dimensions and finite values. Add missing tests and
  a bounded synthetic reader/writer round-trip before any future batch; document
  supported formats and reject unsupported ones without guessing or reshaping.
  Keep single-field Shooting input distinct from PCA cohort import; the latter
  intentionally requires at least two subjects and cannot certify a one-field
  serializer by itself. Exact-runtime round-trip verification remains pending.

Acceptance: the axis-shape entry is visible from the morphospace without searching
below unrelated tools; method labels match recorded analyses; existing verified
endpoints are reused and completed runs remain unchanged. External helper static
review is complete; runtime verification and implementation remain pending. This
backlog does not authorize running that script or a scientific batch.

### Existing delivery sequence

1. **Validation Lab reliability:** responsive opening, frozen-study creation and
   preflight; safe cancellation and explicit launch confirmation. Count the
   entire frozen training-plus-holdout design, separately show backend completion
   and verified evidence, retain original-start wall time across restarts, and
   never call an iteration fraction a measured work fraction or a reliable ETA.
   Verify cancellation races, failed evidence, retries and legacy ledgers.
2. **Large-mesh viewing:** reduced, cached display geometry in every mesh viewer,
   including settled frames; original scientific geometry and exact picking stay
   protected. Explicit original-detail inspection remains available. QC must not
   claim inspection of hidden details. Verify all rendering routes, bounded
   memory/jobs, stale results, source integrity and responsiveness on large meshes.
3. **AFK pilot:** explicit opt-in and a bounded pilot-only scope; automatically
   select eligible stage recommendations with an auditable provisional policy.
   Stop on missing eligibility/hard failure. Preserve cancellation/resume and
   return-to-desk review; never manufacture visual approvals or launch the atlas.
4. **Concise guided workflow:** short next-action summaries, collapsed supporting
   explanations, essential warnings/decisions visible. Include finite GPA review
   navigation and audit the remaining staged-calibration UX checklist.
5. **Engineering handoff:** run regressions and large-mesh UI checks, build and
   verify a private local installer, and record exact code/evidence provenance.
   Installation, public releases and changes to live scientific runs require
   their own user decision; no private datasets or installers go to GitHub.

Each completed package includes a scoped commit/push and a concise English entry
in the existing Google Docs Project log. Partial implementation is not completion.

The AFK pilot now implements the explicit bounded provisional policy described in
`AFK_PILOT.md`. Standard robustness-gated behavior remains available. Default copy
has been shortened in data intake, pilot planning, landmark placement, GPA review,
registration QC, shape-space comparison and report export; detailed explanations
remain in collapsed disclosures and mandatory QC warnings stay visible. These
internal UI changes are not a substitute for independent usability evaluation.

## Larger roadmap: planned work, not automatically completed by this version

Large-mesh viewing is implemented as bounded, cached, display-only quadric
clustering, shared background rendering/loading and explicit original-detail
inspection. See `LARGE_MESH_VIEWER.md` for the measured private-mandible example
and limits: fine anatomical detail can be lost in a proxy, so exact picking and
QC confirmation still require the original view. This is not scientific mesh
decimation, GPU rendering or a hard frame-latency guarantee.

| Workstream | Dependencies and next work | Acceptance gate |
| --- | --- | --- |
| Modern/reference qualification | Review frozen Weevil continuation, then execute the authorized continuation; predeclare numerical and geometric comparisons | Converged, independently recomputed gradient/objective/deformation and performance evidence; inconclusive runs remain inconclusive |
| Scientific parameter validation | Independent anatomical landmarks, PCA/subspace stability, predeclared test/holdout separation | Report uncertainty and sensitivity; no tuning to published PCs or universal-optimum claim |
| Multiresolution analysis | Prospective approved face-count levels and immutable provenance, distinct from display proxies | Compare atlas geometry, residuals, tangent/PCA stability and PC endpoint shapes before recommending scientific decimation |
| Pilot selection/search | Optional biological strata/extremes; bounded adaptive search with explicit attachment/deformation/noise labels | Tail stability tests, boundary-winner regression, safety caps and honest unbounded-search reporting |
| Runtime/memory calibration | Representative small/medium/large cohorts and fresh-process measurements | End-to-end runtime and peak-memory evidence; confidence-calibrated estimates rather than an untested fixed ETA |
| GPU | Identify accessible NVIDIA hardware, memory budget and supported environment; preserve CPU fallback | Same scientific gates plus CPU/GPU parity/tolerance, determinism and failure/memory tests; no GPU speedup claim from CPU tests |
| HPC/Apptainer | Obtain target cluster policy, storage/mounts, scheduler and container support; stage-only dry run first | Reproducible submission, cancellation, restart, path/provenance and data-permission checks on the actual target; NAS storage alone is not compute |
| Linux/macOS CPU | Installed-wheel/offscreen and public synthetic CPU matrix defined in `PLATFORM_COMPATIBILITY.md`; Apple Silicon engine and Intel GUI scopes are separate | Observe the matrix first; native clean-system install/uninstall, interactive GUI and project-preservation evidence remain separate gates |
| Distribution | Review pinned release lock, SBOM and licenses; signing and clean-VM resources | Signed installer and retained-integrity evidence, followed by explicit release authorization |
| External usability and documentation | Recruit independent testers with consent; task-based protocol; update user/method docs | Observed completion/errors, documented limitations, reproducible examples; internal tests do not substitute for external usability evidence |
| Scientific release | Complete qualification, benchmarks, documentation and authors' review | Approved archived release/DOI and manuscript submission; neither is implied by implementing UI features |

These gates have no invented dates or approvals. Hardware access, cluster policy,
independent testers, author decisions and scientific observations are dependencies
to resolve explicitly. Existing roadmap items stay open until their evidence is
actually available.

## Validation Lab implementation notes

The first package adds hash-chained UTC event times for new events, without
rewriting legacy ledgers. If the first execution event was untimed, the UI says
the original start is unavailable instead of using a later resume or file mtime.
Wall time includes interruptions; it is not accumulated compute time. Completed
whole-study wall time stops at the recorded holdout-report completion.

The progress denominator includes every frozen training/resampling run and every
planned fixed-template holdout run, even before holdout input preparation. A local
backend receipt is only an observed backend finish; it does not verify scientific
evidence. Failed postprocessing cannot silently trigger a repeated completed atlas
or registration. Results are not called fully validated until both reports exist.

Opening, source/result verification, protected study preparation, workload checks
and terminal snapshot reloads run off the GUI thread. Cancellation is cooperative
at phase boundaries: a long individual verification/copy may finish before it is
acknowledged, and a valid prepared study may be retained, but no engine launches
after cancellation. Integrity failures are surfaced, not hidden by creating a
fresh replacement study. Existing source/configuration hash gates remain active.
