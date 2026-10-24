# UI text audit — 19 October 2026

Status: **26 source locations revised in v138; independent usability review open.**
The owner's 20 October screenshot adds the still-open UI-27 follow-up below;
the original source pass does not close that report.
The numbered findings below retain the observed problem and reduction target.
The checked items mean the source pass is implemented, not that native first-use
acceptance or installation has passed. Default layouts and help are shortened;
full execution logs, saved scientific reports and optional detailed parameter
references remain available. See [v138 scope](V138_DESKTOP_BACKLOG.md).
Source baseline: `146b520cd8f730addd821a6f5878aa27b1628fbc` on the development
branch; runtime remains v137. This is a source-based review of UI construction,
text updates and visibility conditions, not an interactive acceptance test.
Main workflow pages 1–7 and the supporting dialogs below were examined. A literal
call-site inventory helped locate candidates; length alone was not treated as a
defect. The running application and scientific computations were not operated.

Each item identifies its screen/state, current problem and a proposed reduction.
**Visible** means placed in the normal layout for that state; **expanded** means
supporting text appears only after opening help; **tooltip** means hover help.
Runtime paths and optional engine/legacy routes can affect which controls appear.
Suggested wording records the original audit target; final copy is in the linked source.

## First pass: data, alignment and landmarking

- [x] **UI-01 — Data & engine: repeated opening instructions.** Visible header,
  boundary and footer all explain that inputs/alignment come first. Keep the page
  title, required fields and one state-dependent instruction, such as “Choose a
  mesh folder to begin.” Remove the extra workflow narration.
  [Source: setup page](../src/diffeoforge/desktop/widgets.py#L1930).

- [x] **UI-02 — Open/resume/recover: repeated folder instructions.** Tooltips for
  opening a completed run, resuming and crash recovery each explain run-folder
  layout and filenames. Put the shared folder-selection rule in the picker/help;
  keep each tooltip to its distinct action and prerequisite. Preserve the
  checkpoint requirement and explicit crash-recovery distinction.
  [Source: returning-project controls](../src/diffeoforge/desktop/widgets.py#L1987).

- [x] **UI-03 — GPA preview: technical report inside expanded help.** “Alignment
  details” combines source formats, publication behavior, residual distributions,
  scale ranges and sensitivity prose. Use a small diagnostic table; keep the
  current outcome and required visual-review action outside it. Put the complete
  report in a discoverable local log/report instead of another long paragraph.
  [Source: preview details](../src/diffeoforge/desktop/widgets.py#L6322).

- [x] **UI-04 — GPA viewer: dense help and status strip.** Expanded “How to review
  alignment” mixes inspection instructions, wireframe meaning, proxy rendering
  and unchanged-file assurances in one paragraph. Visible sampling/status labels
  additionally show face/edge counts, residual rank and scale. Keep inspection
  cues and the selected specimen; move rendering/provenance statistics to a
  compact diagnostics view. Shorten overlay labels without losing their meaning.
  [Source: viewer help and controls](../src/diffeoforge/desktop/gpa_review_dialog.py#L60),
  [status](../src/diffeoforge/desktop/gpa_review_dialog.py#L246).

- [x] **UI-05 — Landmark editor: repeated placement/snap explanation.** The visible
  instruction and expanded “Placement, editing and autosave” repeat the original-
  surface snapping rule. The expanded paragraph also mixes editing, proxy methods,
  source preservation and draft behavior. Keep a short placement instruction,
  compact controls help and a clear autosave indicator. Retain the fact that
  Cancel keeps the draft; put detailed coordinate/proxy provenance in logs/help.
  [Source: placement instructions](../src/diffeoforge/desktop/landmark_editor.py#L84).

- [x] **UI-06 — Landmark JSON import: oversized success dialog.** The success
  message combines imported counts, output path, coordinate conventions,
  conversions that were not performed, homology and the next GPA step. Show the
  import result and next action first, with an “Open CSV” action/details. Preserve
  coordinate-frame/unit checks and ignored-file warnings where a decision is
  needed; retain the full import receipt in the local report.
  [Source: import-complete dialog](../src/diffeoforge/desktop/widgets.py#L5213).

- [x] **UI-07 — Feature ruler: long intro for a two-click action.** A visible
  paragraph combines anatomical interpretation, mouse controls and methodological
  caveats before the separate “Click the first endpoint” status. Keep “Select the
  two ends of the smallest feature to preserve,” then the next-click prompt.
  Put gestures in compact help and retain the researcher-defined meaning once.
  [Source: ruler introduction](../src/diffeoforge/desktop/feature_scale_dialog.py#L47).

## Parameter setting and preparation

- [x] **UI-08 — Parameter page: repeated workflow narration.** Subtitle, “Follow
  the green action,” expanded workflow description and calibration-card help
  retell the pipeline. Use one current next action; give buttons concrete names
  rather than referring to their color. Keep a short optional workflow overview.
  [Source: page boundary/help](../src/diffeoforge/desktop/widgets.py#L2088),
  [calibration card](../src/diffeoforge/desktop/widgets.py#L2191).

- [x] **UI-09 — Parameter help: descriptions of an older pilot workflow.** Expanded
  texts say visual reconstruction QC is optional, describe running every candidate
  in a stage, and say selection need not open every reconstruction. Check these
  statements against the active fit-first, required-review route and replace them
  with concise, route-specific guidance. This is a copy-consistency item, not
  authorization to weaken QC or change execution.
  [Source: workflow details](../src/diffeoforge/desktop/widgets.py#L2096),
  [calibration explanation](../src/diffeoforge/desktop/widgets.py#L2191).

- [x] **UI-10 — Parameter explanations: nested walls of text.** Expanded control
  help renders a summary plus several full paragraphs; a separate concept block
  explains the same matching-detail, disparity and deformation distinctions.
  Keep one plain-language sentence, the effect of increasing/decreasing a value
  and at most one useful example. Link longer methods separately; preserve the
  distinction between the three independent settings.
  [Source: help renderer](../src/diffeoforge/desktop/parameter_guidance.py#L16),
  [concept explanation](../src/diffeoforge/desktop/widgets.py#L4465),
  [scrolling help panel](../src/diffeoforge/desktop/widgets.py#L443).

- [x] **UI-11 — Saved preparation reports: repeated read-only/export assurances.**
  Report checking and evidence export have separate multi-clause descriptions
  listing everything they do not open or modify. Use “Check saved report” with a
  short result, one details/log action and a privacy notice at export. Preserve
  the input binding and actual export checks in code/evidence.
  [Source: saved-report panel](../src/diffeoforge/desktop/widgets.py#L2284),
  [review-stage counterpart](../src/diffeoforge/desktop/widgets.py#L2518).

## Pilot and comparison dialogs

- [x] **UI-12 — Pilot header: several layers explain the same next step.** Intro,
  stage question, fresh-pilot three-step card and expanded decision guidance cover
  overlapping workflow instructions. Keep the stage/question and one contextual
  action; reduce the optional overview to a short checklist. Respect the existing
  Stage 4 suppression of generic ranking advice; do not reintroduce that text.
  [Source: guided intro](../src/diffeoforge/desktop/reference_calibration_dialog.py#L1529),
  [stage guidance layout](../src/diffeoforge/desktop/reference_calibration_dialog.py#L1993).

- [ ] **UI-27 — Pilot header and status still repeat the same instructions.**
  Owner screenshot, 20 October 2026: the title "fit → review → combined check",
  the "Fit → review → continue" heading and the sentence "Fit → inspect → approve
  or try again" repeat the workflow. Generic "Pilot task…", "Ready for the first
  specimen" and "Checking saved fits and preparing the next attempt…" also appear
  together. Keep one short stage title, one truthful current activity/progress
  line and one next action; do not show readiness while preparation is active.
  Move the technical "Pilot data" path into details and consolidate overlapping
  help. Preserve required review decisions, progress and actionable errors.
  Verify the fresh/preparing/ready/review states with the owner at normal window
  size. Backlog only; the screenshot does not establish the cause of the status
  mismatch, and no UI repair is claimed.

- [x] **UI-13 — Approved candidate: three copies of the same review state.** With
  fit metrics and a recorded approval, a card can show “Anatomical review approved,”
  checked “Visual QC passed” and “Your review: approved.” Use one current, bound
  review badge with “Review again.” Keep stale/fresh-review requirements explicit.
  [Source: first label](../src/diffeoforge/desktop/reference_calibration_dialog.py#L2686),
  [checkbox and second label](../src/diffeoforge/desktop/reference_calibration_dialog.py#L2787).

- [x] **UI-14 — Candidate help: repeated interpretations and cautions.** Expanded
  “About this option” combines parameter meaning, rationale, automatic check,
  relative-measurement headings, trade-off summary and full trade-off explanation.
  Color/ranking/distance help repeats the anatomy-versus-metric distinction.
  Give one short reason per actionable issue, a compact measurements table and
  one scoped interpretation help. Retain scientific limits without restating
  them for every row and heading.
  [Source: candidate details](../src/diffeoforge/desktop/reference_calibration_dialog.py#L2671),
  [comparison detail](../src/diffeoforge/desktop/reference_calibration_dialog.py#L2718),
  [color legend](../src/diffeoforge/desktop/reference_calibration_dialog.py#L2037).

- [x] **UI-15 — Screened-option chooser: dense permanent explanation.** The visible
  notice explains sorting, sampling uncertainty, regularity, approval preservation
  and the later joint fit beneath an eight-column table. Keep “Choose one kept
  option for the joint test” plus a short metric caveat. Put secondary columns and
  methodology in optional details; retain the explicit choice and later QC.
  [Source: screening notice](../src/diffeoforge/desktop/screening_choice.py#L40).

- [x] **UI-16 — Control-density comparison: two permanent technical paragraphs.**
  An introductory note explains shared bases/zero momenta and a second paragraph
  explains sampled distances, size normalization and scientific limits. Keep the
  comparison table, one next action and one short interpretation note; put basis
  initialization and the full metric definition in details/report. Retain units
  and fresh-review requirements where the choice is made.
  [Source: density introduction](../src/diffeoforge/desktop/control_density.py#L23),
  [second paragraph](../src/diffeoforge/desktop/control_density.py#L65).

## Parameter review and atlas execution

- [x] **UI-17 — Preflight/review: technical wording before a simple readiness
  decision.** “Auditable compute operations,” private-destination headings and
  repeated read-only/no-start assurances obscure whether the engine, memory and
  destination are ready. Use short named check results and a single next action.
  Keep resource shortfalls and destination conflicts visible; put detailed
  verification/provenance in the existing report/log.
  [Source: review introduction](../src/diffeoforge/desktop/widgets.py#L2347),
  [setup-check explanation](../src/diffeoforge/desktop/widgets.py#L2446),
  [execution technical panel](../src/diffeoforge/desktop/widgets.py#L2748).

- [x] **UI-18 — Cohort initialization: repeated specimen/iteration counters.** The
  current activity is assigned to the state label, stage label and optimizer
  description, then appended to the visible event log. This includes the owner's
  reported duplicate. Keep the phase, one compact progress line and the bar;
  expose historical events through a log action.
  [Source: initialization activity](../src/diffeoforge/desktop/widgets.py#L11296),
  [event-log append](../src/diffeoforge/desktop/widgets.py#L11433).

- [x] **UI-19 — Joint optimization: repeated counters plus long running commentary.**
  Iteration/objective appear in the state label, progress bar, optimizer paragraph
  and event log. The paragraph adds rolling-median explanation, forecast caveats,
  cap scenario and resources. Show each key value once; keep one clearly qualified
  time estimate and any current slowdown warning. Put estimator methodology,
  secondary components and historical messages in optional diagnostics/logs.
  [Source: optimizer progress](../src/diffeoforge/desktop/widgets.py#L11404).

- [x] **UI-20 — Completion: long stop explanations repeat evidence terminology.**
  Individual completed/capped/tolerance branches each render a paragraph about
  independent verification, visible final iteration and scientific limits.
  These branches are alternatives, not simultaneous duplicates. Use a short
  stop reason, iteration, elapsed time and next action. Keep the final-step logging
  limitation and scientific interpretation in one concise details section.
  [Source: terminal result text](../src/diffeoforge/desktop/widgets.py#L11851).

## QC, results, exports and visualization

- [x] **UI-21 — Atlas QC: overlapping intro, boundary and expanded limitations.**
  The visible subtitle and boundary both ask for required-case decisions, followed
  by release status. Expanded help additionally combines inspection, exploratory
  results, navigation, PCA filtering and proxy limitations. Keep the current
  required action/count, concise inspection guidance and a short explanation of
  blocked release. Keep uncertain/failed cases and original-detail requirements
  visible; split other topics into targeted help/report sections.
  [Source: QC page](../src/diffeoforge/desktop/widgets.py#L3595).

- [x] **UI-22 — Results header/provenance: hashes and paths lead the page.** The
  subtitle explains byte/SHA checks, the boundary explains scientific limits,
  and the visible “Bound result snapshot” includes full paths and two hashes.
  Lead with the result, stop state and available next actions. Put full paths,
  identifiers and hashes in a compact provenance/details view with copy/open
  actions. Preserve actionable QC warnings and access verification.
  [Source: results header/card](../src/diffeoforge/desktop/widgets.py#L2888),
  [filled provenance text](../src/diffeoforge/desktop/widgets.py#L11841).

- [x] **UI-23 — PCA/shape-space help: method essays repeated across panels.**
  Expanded PCA-method help, “How DiffeoForge uses this evidence” and the comparison
  dialog explain overlapping tangent metrics, PCoA, RBF differences and validation
  limits. Keep a short description per method and link one shared methods/report
  reference. Retain the active method/units and distinctions needed for the
  selected comparison; do not equate unlike variance measures.
  [Source: PCA method help](../src/diffeoforge/desktop/widgets.py#L3235),
  [comparison explanation](../src/diffeoforge/desktop/widgets.py#L3297),
  [method-selection dialog](../src/diffeoforge/desktop/widgets.py#L1239).

- [x] **UI-24 — Reports/exports/artifacts: repeated descriptions of internal work.**
  Report, publication bundle, metadata and artifact sections each explain output
  contents, immutability, rechecking or what is not rerun. Ready-state labels add
  further paragraphs. Use the deliverable name, destination and a short current
  state; offer file-format/contents help and logs on demand. Preserve privacy,
  overwrite choices and unsupported-claim warnings at the relevant action.
  [Source: export sections](../src/diffeoforge/desktop/widgets.py#L3439),
  [artifact explanation](../src/diffeoforge/desktop/widgets.py#L3541),
  [ready-state messages](../src/diffeoforge/desktop/widgets.py#L11909).

- [x] **UI-25 — Validation Lab: overlapping progress totals and dense methods.**
  Progress-bar text, accounting label, design summary and active status each
  expose counts. Expanded scope help adds a long methods/limitations paragraph;
  a completed comparison can also have a second generic completion message.
  Show the current phase and verified/total once, highlight failures requiring
  action, and move detailed accounting/design to a table/log. Preserve the
  distinction between backend-finished, evidence-verified and report-complete.
  [Source: scope help](../src/diffeoforge/desktop/reference_validation_dialog.py#L171),
  [progress/accounting](../src/diffeoforge/desktop/reference_validation_dialog.py#L294),
  [completion/next action](../src/diffeoforge/desktop/reference_validation_dialog.py#L383).

- [x] **UI-26 — Visualization: expanded methods mix operation and provenance.**
  One paragraph combines native samples, interpolation, proxies, heatmap ranges,
  coordinate units, signed normals and PCA-sign convention. Keep units and color/
  sign interpretation close to the relevant view. Reduce general help to short
  bullets and put sampling/rendering provenance in a method note/local report.
  [Source: visualization methods](../src/diffeoforge/desktop/visualization_panel.py#L127).

## Remaining independent acceptance

- Each live status/counter has one primary location per screen; history remains
  available through an obvious log action. Logs are not a substitute for an
  actionable error or a decision the user must make now.
- Default screens show the current outcome and next action. Expanded help is
  also edited for brevity; moving the same essay behind a toggle is insufficient.
- Use natural, concrete language. Remove stock reassurance, repeated negative
  clauses and unnecessary “verified/bound/immutable” wording from routine copy.
- Keep anatomical/QC requirements, numerical stop distinctions, units, upload/
  overwrite decisions and failure causes accurate and visible at the relevant
  action. Internal verification, scientific evidence and original logs stay intact.
- Check representative fresh/reopened/busy/completed/error states, expanded help
  and smaller windows with a user. This audit does not claim that acceptance.

## Checks against false positives

The shared fit-preference panel already hides its own title/color intro when
embedded in fit inspection; these literal copies are not listed as a visible
duplicate. Stage 4 already hides generic ranking advice in favor of a contextual
next step. Engine-specific and stop-specific text branches are not counted as if
they were all shown together. Essential legends and context-specific warnings
are not candidates for blanket removal.
