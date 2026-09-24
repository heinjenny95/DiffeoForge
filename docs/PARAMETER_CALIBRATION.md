# Transparent Deformetrica parameter calibration

Status: **implemented deterministic planning, broad combined kernel screening,
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
5. Choose the requested pilot-subject count. Optionally load a CSV with the
   exact columns `filename,stratum,is_extreme`, then build the calibration
   plan. DiffeoForge refuses an undersized pilot rather than silently omitting
   a declared extreme or stratum.
6. Review or export the self-contained methods report.
7. Create the project. The recommendation and calibration-plan fingerprints
   are embedded in `atlas.yaml`.
8. After the automatic Deformetrica setup check passes, open **Automatic
   Deformetrica pilot calibration**.
9. Select **Run complete four-stage pilot** once. DiffeoForge first screens
   attachment and deformation scales together, then refines deformation, noise,
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
measurement, pilot count, or biological pilot declarations invalidates the
current plan.

## Representative pilot selection

The template is excluded. Each subject is described by bounding-box diagonal,
root-mean-square radius, median sampled edge length, point count, and face
count. Robustly scaled descriptors are used to select:

1. the descriptor medoid;
2. successive farthest-first descriptor extremes.

Filename ordering resolves exact ties. The same bytes and settings therefore
produce the same selection and fingerprint. This is deliberately described as
a geometric-diversity heuristic.

When sex, species, treatment, locality, known morphology, or another manuscript
factor matters, the optional declaration CSV adds researcher-authored evidence
before selection. Every row names one exact subject and may assign a stratum,
mark the subject as an explicit biological extreme, or both. Selection then:

1. includes every declared extreme;
2. adds a deterministic within-stratum medoid for each stratum not already
   represented by an included extreme;
3. adds the whole-cohort descriptor medoid when space remains; and
4. fills remaining slots by the unchanged farthest-first geometry rule.

The plan, fingerprint, JSON, HTML methods report, and eventual pilot study bind
the normalized declarations and each subject's selection role. Unknown or
duplicate filenames, inconsistent stratum spelling, invalid boolean values,
and a pilot count too small for the declared coverage fail explicitly. A
stratum declaration guarantees pilot inclusion coverage only; it does not
prove biological representativeness or make the labels outcomes for automatic
parameter scoring.

## Sequential stages

Only one parameter block changes in each stage. Values selected in earlier
stages remain locked.

### 1. Surface-detail and deformation-scale screen

The attachment center is the measured smallest relevant feature. If no feature
is measured, the declared fine/balanced/coarse intent supplies the center. It
is not silently raised to the four-edge sampling diagnostic. Six
logarithmically spaced attachment scales span the declared center, the median
mesh edge, and the conservative four-edge scale. Each is paired with local,
center, and global deformation screens, producing 18 combined candidates.
Together with five deformation refinements, five noise candidates, and three
time-point candidates, the standard strict pilot contains 31 resumable atlas
runs. This is intentionally a scientific calibration workload rather than a
quick preset picker.

The combined screen prevents a superficially attractive attachment width from
being evaluated under only one arbitrary deformation width. Finer-than-four-
edge candidates remain allowed, but their sampling sensitivity is measured and
reported.

### 2. Deformation locality and control density

Five logarithmically spaced candidates refine the declared
local/balanced/global deformation range after the combined screen. Deformation
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
other selected stage values fixed. The desktop asks the researcher to declare
the feasible outward limit for every affected parameter, previews the new
candidates and destination, and then creates a separately bound successor
study and starts it. The proposal itself remains a planning artifact: its displayed
candidates have not been executed and are not represented as safe until that
successor runs them and combines their evidence with the preserved source
pilot. Preserved candidates stay complete, so only the newly added neighbors
execute before reassessment.

The declared feasibility limits apply to the complete outward-search lineage,
not just its first successor. If the preferred value remains on the new search
boundary, the automatic route derives another deterministic immutable sibling,
imports the already verified evidence, and runs only its new neighbors. This
continues until the winner is interior or the declared safety limit prevents a
further candidate. It fails closed rather than overwriting an existing sibling,
crossing a safety limit, inventing a wider limit, or describing a boundary
winner as an enclosed optimum. Every successor records its round number,
lineage root, limits, hashes, and source event chain.

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

If an attachment/deformation/control-spacing winner remains on a tested
boundary, freeze a successor only after declaring a positive feasibility
interval for every reported boundary parameter:

```powershell
diffeoforge reference-calibration-study-extend `
  "C:\project\calibration\pilot" `
  --output "C:\project\calibration\pilot-attachment-extension-01" `
  --limit attachment_kernel_width=0.001:0.6 `
  --limit deformation_kernel_width=0.01:1.2 `
  --limit initial_control_point_spacing=0.01:1.2 `
  --outward-steps 2

diffeoforge reference-calibration-study-run `
  "C:\project\calibration\pilot-attachment-extension-01"
```

For a noise-boundary successor, supply only its reported parameter, for
example `--limit noise_std=0.0001:0.5`. The command refuses missing, duplicate,
unordered, or exceeded limits and never overwrites a destination. It copies
the bound pilot inputs, imports completed source metrics with their event
hashes, and prepares configs for the combined candidate set. The ordinary
study runner skips preserved candidates and executes only the new outward
neighbors. With `--complete`, it automatically creates further deterministic
successors while the winner remains on a boundary and the inherited limits
permit another outward step. Loading or continuing any successor fails closed
if the cited source manifest or event chain changes.

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

### Targeted follow-up when one reconstruction is implausible

A large deformation is not, by itself, an anatomical failure. The regularity
term is part of the model's fit-versus-complexity trade-off, not a biological
verdict. Increasing expected disparity does not guarantee a defensible fit.
Inspect the original and reconstructed surface, alignment, input identity,
topology, local distortion and optimizer stop signal together. Check whether
the problematic specimen was actually included in the original pilot subset.

Before repeating an entire atlas, a bounded **in-sample diagnostic** can isolate
the attachment/regularity trade-off:

1. Preserve the completed atlas, its QC decisions and PCA unchanged. Copy and
   hash-bind its learned template, control points and selected aligned inputs
   into a separate diagnostic directory. Include the problematic specimen and
   explicitly chosen comparison specimens; unreviewed is not equivalent to
   visually approved.
2. Freeze both the learned template and control points. Use identical initial
   momenta, subject order, runtime, integration settings and optimization caps
   for every candidate. Default zero-momentum initialization is not a resume
   of the original fitted momenta and can follow a different optimizer path.
3. First vary only noise standard deviation, for example the existing value,
   half and one quarter. In the same attachment model these multiply the
   attachment coefficient by 1, 4 and 16; they do not guarantee correspondingly
   improved geometry. Kernel widths and control-point spacing stay fixed.
4. Compare geometric residuals, anatomical overlays, distortion and convergence
   per specimen. Do not rank different noise settings by raw total objective
   values, because the objective's weighting changes. Stop on execution failure;
   do not silently expand the grid or approve QC.

This diagnostic is conditional on the old atlas and uses previously fitted
subjects. It is neither an untouched holdout test nor a new group atlas. A
promising setting still needs a common full-cohort run and human QC. Do not
replace one subject's momenta with a separately tuned fit and present the mixed
results as the original coherent atlas morphospace. If attachment weighting is
insufficient, investigate deformation scale, initialization/template dependence
or a topology mismatch in a separately declared comparison.

For preliminary mesh-symbol morphospaces, retain the exported scores and their
method identity. State whether symbols depict observed meshes or model
reconstructions, use a common view, disclose any per-symbol size normalization,
and use leaders when symbols are displaced for readability. Carry unresolved
QC caveats forward; a communication figure does not approve an atlas.

### Matching-detail follow-up when local projections remain mismatched

A lower global surface-distance summary can coexist with a persistent local
anatomical error. A reconstructed surface is a deformed template, not a newly
segmented copy of the observed surface. Inspect the initial template, learned
template, observation and reconstruction in identical views when an unwanted
projection persists. Preserved mesh connectivity does not, by itself, imply
that the number of geometric protrusions must remain unchanged.

After an attachment-weight diagnostic, a separately authorized, bounded 2x2
comparison can test matching detail: halve and quarter the original attachment
kernel width, each paired with the previously examined half and quarter noise
standard deviation. Use the same declared in-sample cohort, learned template,
explicit control points, zero-momentum initialization and numerical limits.
Keep the template and control points frozen. Verify that only the two declared
parameters and administrative paths differ; preserve existing runs and reviews.
Execute the four candidates sequentially, stop on failure, and do not retry or
expand the grid automatically. Check disk headroom before every candidate.

Changing attachment width changes the data-term geometry and scale. The 4x and
16x noise-coefficient labels apply relative to the original noise at a fixed
attachment kernel; they do not imply equal effective fit strength across
kernels. Compare geometric and anatomical evidence, not raw total objectives.

Evaluate both directions of local surface mismatch, higher-percentile tails,
common-view overlays, template-relative distortion and numerical stop evidence.
Declare regions of interest from the observations before comparing candidate
outcomes, and report their definitions and sample counts. Check all comparison
specimens: a better global p95 can hide a worse p99 or a displaced local feature.
Neither a small global error nor no detected triangle self-intersections is
anatomical approval or proof of correct correspondence.

For an exploratory elongated-surface comparison, geometric end bands can be
defined from the observed surface's area-weighted longest principal axis, for
example the first and last 20% of its projected span. Fix the origin, axis sign,
cutoffs, view and scale for each observation before inspecting the new candidates.
These are geometric regions, not homologous anatomical landmarks; tied leading
eigenvalues and features outside the bands require explicit visual review.
Do not recalculate a separate coordinate frame or size normalization for each
reconstruction. Document any later region changes as sensitivity analyses.

Sample uniformly by triangle area in each direction. Assign each source sample
to its region, but measure distance to the **complete** opposite surface, not a
cropped target. Report both directions and their sample counts separately. If
pooling regional distances, give each direction half the total probability mass;
unequal region counts must not silently change that weighting. Specify the
quantile convention. An empty direction is undefined, and sparsely sampled tail
quantiles must be flagged rather than ranked. Repeat with an independent seed
to assess sampling sensitivity, not biological uncertainty. A sampled maximum
is not the exact Hausdorff distance. Keep quantitative distances on the full
triangulations even when overview rendering uses documented display copies.

If matching detail is insufficient, investigate deformation resolution with
adequate control-point support, or template dependence, in another separately
declared experiment. These are not implicit next jobs. A final common-cohort
atlas, human QC and shape-space stability comparison remain separate steps;
do not mix independently tuned subject momenta into one atlas PCA.

### Bounded deformation-support follow-up

With explicit authorization, separate support density from deformation scale
using two fixed-template diagnostic cases. Retain the previous matching settings
and original control-point coordinates; add a deterministic, padded lattice at
half the reference deformation width. Use the same explicit enlarged support
in both cases: first retain the reference deformation width, then halve it.
An explicit control-point file takes precedence over an initialization-spacing
setting: changing spacing alone does not densify a supplied point set.

Record lattice origin, bounds, padding, spacing, point count, deduplication rule
and template coverage; verify finite coordinates, original-point retention and
resource caps before launch. Hash-bind the explicit point file and confirm its
path in the generated engine XML. Use independent zero-momentum starts with the
same optimizer and numerical limits. Retaining the old basis at the old width
preserves its representability, not a guarantee of optimizer success. A narrower
deformation kernel changes the metric and regularization as well as locality.

Reuse the declared observation regions, full-resolution bidirectional distances,
common-view anatomy checks and comparison specimens. Run only the bounded cases,
sequentially, with stop-on-failure and no automatic parameter adoption. A promising
finer deformation still needs integration-sensitivity checks, anatomical review
and a common-cohort atlas before interpreting a replacement morphospace. Keep
template and optimizer-initialization effects separate from this comparison.

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
