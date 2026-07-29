# Transparent Deformetrica parameter calibration

Status: **implemented deterministic planning, automatic sequential candidate
execution, verified automatic QC evidence extraction, optional visual QC, and
researcher-gated stage selection. Scientific validation is still prospective.**

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
9. Start the current stage once. DiffeoForge runs all pending candidates
   sequentially and retains already completed candidates if execution is
   continued later.
10. Read the plain-language question, parameter value, and direction-of-change
    explanation on each candidate card. Relative automatic observations such
    as closest surface match, least atlas area change, lowest deformation cost,
    and fastest pilot run are displayed as explained color-coded rows. Green
    marks a favorable automatic signal, yellow marks a context-dependent
    trade-off, and red marks an unfavorable relative signal. Each row explains
    the interpretation limit; colors describe one measurement at a time and
    never identify an automatic winner.
11. Select one automatically valid candidate from the green menu using the
    explained evidence and the needs of the study. DiffeoForge records this
    explicit researcher selection and only then prepares the next stage with
    earlier values locked. Technical measurements remain optional secondary
    information.
12. Optionally open **Visual QC** for any candidate when a reconstruction
    comparison would help. Blue wireframes show the exact bound original pilot
    meshes and orange surfaces show their Deformetrica reconstructions in the
    same rotatable camera. A recorded visual pass keeps the candidate eligible;
    a recorded visual failure excludes it. Not performing visual QC does not
    prevent selection.
13. When visual QC is performed, open every required pilot-specimen pair before
    recording a pass or failure. DiffeoForge stores `passed`, `failed`, or
    `not_performed` for every option in the append-only stage provenance.
14. After stage four, switch the main workflow to
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

### 1. Surface-matching detail

The center is the measured smallest relevant feature, bounded below by the
mesh-sampling floor. If no feature is measured, the declared fine/balanced/
coarse starting intent supplies the center. Neighboring candidates test a
detail-first, center, and smoother setting.

Retain the largest attachment width that still preserves the predeclared
feature without systematic residual structure. A value below the sampling
floor is never proposed.

### 2. Deformation locality and control density

Candidates are centered on the declared local/balanced/global deformation
intent. Deformation width and initial control-point spacing move together.

Choose the smoothest deformation whose residual map does not retain relevant
structure. A move to a smaller, more local model is an explicit researcher
decision, not an automatic conclusion.

### 3. Data fit versus regularity

Noise candidates test fit-first, center, and regularity-first weights.
Candidate evidence is evaluated as a Pareto problem using residual,
deformation-energy, distortion, and runtime metrics.

DiffeoForge exposes all Pareto candidates. Its weighted balanced score is a
navigation aid with recorded weights, never an automatic scientific selection.
A candidate is ineligible if execution, convergence, mesh validity, or required
metrics fail. Visual QC is optional, but an explicitly recorded visual failure
also makes that candidate ineligible.

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
  "C:\project\calibration\pilot"

diffeoforge reference-calibration-study-status `
  "C:\project\calibration\pilot"

diffeoforge reference-calibration-study-review `
  "C:\project\calibration\pilot" `
  --select attachment-02
```

Use repeatable `--approve CANDIDATE_ID` or `--reject CANDIDATE_ID` arguments
only when optional visual QC was actually performed. Omitting both records the
visual-review status as `not_performed`.

`study.json` and its SHA-256 bind the plan, copied pilot inputs, source
configuration, launcher, and pilot iteration cap. `events.jsonl` is an
append-only hash chain containing candidate attempts, verified metrics,
optional visual-QC status, and selections. Cancellation never overwrites a run: completed
candidates remain complete, and continuing creates a new immutable attempt for
the interrupted candidate.

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

The workflow automates computation and evidence collection, not anatomical
judgment. The balanced multi-metric score is shown only as a navigation aid.
It cannot select a candidate, and missing convergence evidence, invalid
faces, missing metrics, or an explicitly failed optional visual review make a
candidate ineligible. A visual review that was not performed is recorded as
such and does not by itself make a candidate ineligible. The original plan remains an immutable `planned_not_executed`
declaration; the selected full-cohort configuration additionally carries a
separate completed calibration result bound to the final researcher-decision
event. No safe-preset or biological-validity claim exists until prospective
full-cohort and external validation are complete.
