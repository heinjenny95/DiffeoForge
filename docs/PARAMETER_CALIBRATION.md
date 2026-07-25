# Transparent Deformetrica parameter calibration

Status: **implemented deterministic planning and fail-closed evidence
assessment; candidate execution is not yet automated.**

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
| Pilot evidence | residuals, deformation cost, distortion, runtime, visual review | generalization until full-cohort confirmation |

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
navigation aid with recorded weights, never an automatic scientific approval.
A candidate is ineligible if execution, convergence, mesh validity, required
metrics, or visual approval is missing.

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

The same non-executing plan can be generated without Qt:

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

## Scientific and implementation boundary

The current release builds, embeds, exports, and verifies the plan. It also
contains a deterministic fail-closed stage-assessment core for future result
ingestion. It does not yet schedule the candidate runs or extract every
registration/distortion metric automatically. The status remains
`planned_not_executed` until that separate execution workflow exists and is
validated.
