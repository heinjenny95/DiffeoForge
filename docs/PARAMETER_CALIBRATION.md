# Transparent Deformetrica parameter calibration

Status: **implemented deterministic planning, broad joint kernel screening,
automatic candidate execution, subject-level and reconstruction-wide QC,
weight-sensitivity and subject-bootstrap robustness gates, optional visual QC,
and one-operation uncertainty-qualified reporting. Full-cohort and external
biological validation remain required before a manuscript claim.**

## Why this workflow exists

There is no universally correct Deformetrica kernel width. Attachment width
defines the surface detail used by the matching term. Deformation width defines
the spatial correlation of motion. Control-point spacing changes model
resolution and computational cost. Noise standard deviation changes the
relative weight of data fit and deformation regularity.

Mesh size and sampling constrain defensible candidates, but they do not reveal
which anatomical features matter to a biological question. DiffeoForge
therefore keeps three sources of information separate:

| Source | What it contributes | What it cannot prove |
| --- | --- | --- |
| Aligned meshes | physical scale, sampling floor, geometric diversity | biological relevance or correspondence quality |
| Researcher intent | feature scale and local/global deformation question | registration success |
| Pilot evidence | residuals, deformation cost, distortion, runtime, optional visual review | generalization until full-cohort confirmation |

## Desktop workflow

1. Import meshes that are already GPA-aligned, or complete and approve
   DiffeoForge landmark GPA.
2. Choose the surface-detail and deformation-scale research intents.
3. Select **Analyze aligned meshes**. This is read-only.
4. Optionally select **Measure on 3D template** and click the two endpoints of
   the smallest feature that the atlas should preserve. The Euclidean distance
   is stored in the declared coordinate unit.
5. Choose the requested pilot-subject count and build the calibration plan.
6. Review or export the self-contained methods report.
7. Create the project. The recommendation and calibration-plan fingerprints
   are embedded in `atlas.yaml`.
8. After the automatic Deformetrica setup check passes, open **Automatic
   Deformetrica pilot calibration**.
9. Select **Run complete four-stage pilot** once. DiffeoForge first screens
   attachment and deformation scales jointly, then refines deformation, noise,
   and time points. The search is logarithmically spaced around the biological
   priorities declared in step 2 and crosses the conservative mesh-sampling
   diagnostic. Already completed candidates are retained if execution is
   continued later.
10. At each stage, DiffeoForge rejects candidates with failed execution,
    missing convergence evidence, invalid atlas or reconstruction faces, or
    incomplete metrics. It computes the Pareto front but does not trust one
    hand-set weighting. The same decision is repeated across predeclared weight
    perturbations, an independent weighted-rank aggregation, and deterministic
    pilot-subject bootstraps. Automatic selection is permitted only after the
    robust gate passes and the preferred attachment, deformation,
    control-spacing, and noise values are interior to their tested ranges. A
    minimum/maximum winner is explicitly reported as `search range not
    bounded`; it requires outward evidence or a recorded provisional researcher
    decision even when its within-grid evidence grade is robust. Otherwise the
    stage is explicitly `sensitive` or `ambiguous` and requires additional
    evidence or a recorded researcher decision.
11. After stage four, read the concise recommended values and open the complete
    HTML report. It explains what every parameter changes, how each stage was
    evaluated, all tested alternatives and scores, limitations, and the required
    full-cohort confirmation. A deterministic JSON version is stored beside it.
12. Optionally enable **Advanced mode** before starting to pause after each
    stage and select every candidate manually. Relative automatic observations
    such as closest surface match, least atlas area change, lowest deformation
    cost, and fastest pilot run then appear as explained color-coded rows.
13. Optionally open **Visual QC** for any candidate when a reconstruction
    comparison would help. Blue wireframes show the exact bound original pilot
    meshes and orange surfaces show their Deformetrica reconstructions in the
    same rotatable camera. A recorded visual pass keeps the candidate eligible;
    a recorded visual failure excludes it. Not performing visual QC does not
    prevent selection.
14. When visual QC is performed, open every required pilot-specimen pair before
    recording a pass or failure. DiffeoForge stores `passed`, `failed`, or
    `not_performed` for every option in the append-only stage provenance.
15. After stage four, switch the main workflow to
    `selected/atlas-calibrated.yaml` and review it before the required
    full-cohort confirmation run.

Changing meshes, template, GPA evidence, units, research intent, feature
measurement, or pilot count invalidates the current plan.

## Representative pilot selection

The template is excluded. Each subject is described by bounding-box diagonal,
root-mean-square radius, median sampled edge length, point count, and face
count. Robustly scaled descriptors are used to select:

1. the descriptor medoid;
2. successive farthest-first descriptor extremes.

Filename ordering resolves exact ties. The same bytes and settings therefore
produce the same selection and fingerprint. This is deliberately described as
a geometric-diversity heuristic. If sex, species, treatment, locality, or
another manuscript factor matters, the study must additionally predeclare
stratified representation.

## Sequential stages

Only one parameter block changes in each stage. Values selected in earlier
stages remain locked.

### 1. Joint surface-detail and deformation-scale screen

The attachment center is the measured smallest relevant feature. If no feature
is measured, the declared fine/balanced/coarse intent supplies the center. It
is not silently raised to the four-edge sampling diagnostic. Six
logarithmically spaced attachment scales span the declared center, the median
mesh edge, and the conservative four-edge scale. Each is paired with local,
center, and global deformation screens, producing 18 joint candidates.
Together with five deformation refinements, five noise candidates, and three
time-point candidates, the standard strict pilot contains 31 resumable atlas
runs. This is intentionally a scientific calibration workload rather than a
quick preset picker.

The joint screen prevents a superficially attractive attachment width from
being evaluated under only one arbitrary deformation width. Finer-than-four-
edge candidates remain allowed, but their sampling sensitivity is measured and
reported.

### 2. Deformation locality and control density

Five logarithmically spaced candidates refine the declared
local/balanced/global deformation range after the joint screen. Deformation
width and initial control-point spacing move together.

The automatic route compares the declared-intent-centered candidates using the
published multi-metric assessment. Any move toward a smaller, more local model
is explicitly reported as a provisional evidence-based recommendation, not an
automatically discovered biological truth.

### 3. Data fit versus regularity

Noise candidates test fit-first, center, and regularity-first weights.
Candidate evidence is evaluated as a Pareto problem using residual,
deformation-energy, distortion, and runtime metrics.

DiffeoForge exposes all Pareto candidates. The base balanced score has recorded
weights, but automatic selection additionally requires stability under weight
perturbation, independent rank aggregation, and pilot-subject bootstrap. A
single score is never represented as automatic scientific validation.
A candidate is ineligible if execution, convergence, mesh validity, or required
metrics fail. Visual QC is optional, but an explicitly recorded visual failure
also makes that candidate ineligible.

For the attachment, deformation/control-spacing, and noise stages, DiffeoForge
also compares the provisional winner with the exact minimum and maximum values
present in the immutable plan. The assessment stores `bounded`, `not_bounded`,
or `not_evaluated` plus machine-readable `parameter:minimum` and
`parameter:maximum` flags. A boundary result can still be Pareto-optimal and
robust within the tested grid, but it cannot be described or automatically
used as an enclosed optimum.

The **Collect more evidence** action deterministically derives up to two
logarithmic neighbors beyond each winning boundary. Deformation width and
control-point spacing remain coupled. The proposal has its own SHA-256
fingerprint bound to the immutable source plan and assessment, and holds all
other selected stage values fixed. It is deliberately a planning artifact:
the displayed candidates have not been executed and are not represented as
safe until a separately bound successor study declares feasibility limits,
runs them, and combines their evidence with the preserved source pilot.

### 4. Numerical integration accuracy

The selected scientific parameters remain fixed while 10, 20, and 30 time
points are compared. Choose the smallest count whose atlas, objective, and
residuals agree with the next finer discretization within predeclared
tolerances.

## Full-cohort gate

Before manuscript use:

1. repeat the selected settings on the complete full-resolution cohort;
2. inspect every registration-quality outlier;
3. document convergence or the iteration cap;
4. compare atlas geometry and PCA subspaces with neighboring retained settings;
5. record final researcher approval separately from the pilot plan.

Passing the pilot robustness gate means that the winner is stable **within the
tested pilot design**. It does not prove universal optimality. A strong methods
claim must report the tested search domain, QC metrics, robustness thresholds,
ambiguous stages, full-cohort confirmation, and any independent anatomical
landmarks or biological group labels used for external validation.

## Reproducible command line

The same plan and execution state machine can be used without Qt. First create
or embed the plan, then initialize a study from the resulting project YAML:

```powershell
diffeoforge reference-calibration-plan "C:\aligned-meshes" `
  --units millimeter `
  --surface-detail fine `
  --deformation-scale local `
  --smallest-relevant-feature 0.18 `
  --pilot-subjects 8 `
  --output "C:\study\parameter-calibration"
```

The mesh folder may contain supported VTK, PLY, OBJ, or STL surfaces. By
default, the command requires one unambiguous file named `template` and treats
the other supported files as subjects. Use `--template` and
`--subject-pattern` to make the selection explicit.

Outputs:

- `parameter-calibration-plan.json`;
- `parameter-calibration-plan.html`;
- `parameter-calibration-plan.sha256`;
- `aligned-mesh-recommendation.json`, containing the complete geometry
  observations to which the plan fingerprint is bound.

An existing export is never replaced unless `--force` is supplied.

```powershell
diffeoforge reference-calibration-study-init "C:\project\atlas.yaml" `
  --output "C:\project\calibration\pilot" `
  --pilot-max-iterations 150

diffeoforge reference-calibration-study-run `
  "C:\project\calibration\pilot" `
  --complete

diffeoforge reference-calibration-study-status `
  "C:\project\calibration\pilot"

diffeoforge reference-calibration-study-review `
  "C:\project\calibration\pilot" `
  --select attachment-02
```

`--complete` is the standard one-operation route. Omit it to run only the
current stage, then use `reference-calibration-study-review` for the advanced
manual route.

Use repeatable `--approve CANDIDATE_ID` or `--reject CANDIDATE_ID` arguments
only when optional visual QC was actually performed. Omitting both records the
visual-review status as `not_performed`.

`study.json` and its SHA-256 bind the plan, copied pilot inputs, source
configuration, launcher, and pilot iteration cap. `events.jsonl` is an
append-only hash chain containing candidate attempts, verified metrics,
optional visual-QC status, automatic or manual selection mode, and selections.
The completed study adds `selected/pilot-calibration-report.json` and
`selected/pilot-calibration-report.html`, both hash-bound by the terminal event.
Cancellation never overwrites a run: completed candidates remain complete, and
continuing creates a new immutable attempt for the interrupted candidate.

Automatic evidence currently includes:

- an explicitly labelled symmetric nearest-vertex surface-distance QC proxy,
  using deterministic bounded sampling; this is not Deformetrica's Current or
  Varifold attachment objective;
- resampling-sensitivity of that geometric proxy;
- final logged attachment and regularity magnitudes;
- final-atlas triangle validity and p95 absolute log area distortion relative
  to the starting template;
- explicit Deformetrica optimizer stop-signal classification and runtime;
- neighboring-atlas RMS and relative objective/residual differences for the
  integration stage.

The desktop keeps these exact technical measurements behind **Show technical
measurements** so a new user first sees the experimental question and the
observed trade-off. Progressive disclosure changes presentation only: the
verified values and their interpretation limits remain available and
selectable for methods reporting.

## Scientific and implementation boundary

The workflow automates computation and a transparent provisional parameter
recommendation, not anatomical judgment. The balanced multi-metric score can
select an eligible candidate in the standard route because the candidate set is
already centered on the researcher's declared priorities. Its weights and
selection mode are preserved, and the report explicitly states that this is not
biological validation. Missing convergence evidence, invalid faces, missing
metrics, or an explicitly failed optional visual review make a candidate
ineligible. A visual review that was not performed is recorded as such and does
not by itself make a candidate ineligible. The original plan remains an
immutable `planned_not_executed` declaration; the selected full-cohort
configuration carries a separate completed calibration result bound to the final
selection event. No safe-preset or biological-validity claim exists until
prospective full-cohort and external validation are complete.
