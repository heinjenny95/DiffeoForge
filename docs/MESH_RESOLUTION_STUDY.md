# Prospective scientific mesh-resolution study

This optional research workflow compares explicitly prepared and approved
scientific mesh levels. It does not turn display proxies into scientific inputs,
simplify originals, select tolerances or start computations for the researcher.

1. Prepare 2–10 levels with identical ordered specimen names and units. Retain
   each original file and record every derived mesh's method, tool version and
   parameters. Use the same scientific/model/runtime settings at each level.
2. Predeclare the reference (highest median subject face count), PCA component
   count and every stability tolerance. Approve the complete plan JSON.
3. In Results & PCA → Scientific mesh-resolution study, choose **Create from
   study plan**. Alternatively use the CLI below. This produces protected level
   configs containing the design fingerprint. Use those exact configurations for
   explicit atlas runs; already completed unrelated runs cannot be relabelled as
   prospective evidence.
4. Open the frozen study, assign a completed run to every level, then choose
   **Assess and create report**. Each report is a separate JSON/HTML/checksum
   directory. No source run or earlier report is overwritten.

```sh
diffeoforge mesh-resolution-study-create approved-plan.json --output mesh-study
diffeoforge mesh-resolution-study-assess mesh-study assignments.json --output assessment-01
```

`assignments.json` maps each level ID to its completed run path. The GUI offers
folder selection instead. Configurations in `mesh-study/levels` can be opened
through the normal DiffeoForge project/review workflow; run start remains explicit.

## Plan fields

The JSON root declares `study_version: "0.1"`, `researcher_approved: true`,
`reference_level`, `components` (1–10), `thresholds`, and `levels`. Level IDs use
lowercase letters, digits and hyphens, starting with a letter. Each level contains
`id`, `config` and `provenance`.

Every provenance row contains absolute `derived` and `source` file paths,
`method`, `tool_version`, and a `parameters` object. Include the template and every
subject exactly once, including explicit identity copies at the reference level.
The same named specimen must derive from identical original source bytes across
levels. Configuration paths may be relative to the plan JSON. No mesh files or
configuration files are edited in place.

All six thresholds must be finite, positive, researcher-selected numbers:

| Key | Definition and passing condition |
| --- | --- |
| `template_p95_mesh_units` | Symmetric sampled nearest-vertex atlas distance p95, at or below the limit |
| `residual_p95_change_mesh_units` | Maximum absolute change of paired per-specimen residual p95, at or below the limit |
| `tangent_distance_relative_error` | Frobenius norm of pairwise tangent-distance changes divided by the reference distance-matrix norm, at or below the limit |
| `minimum_score_cka` | Linear CKA of the declared leading PCA scores, at or above the threshold in (0,1] |
| `maximum_score_subspace_angle_degrees` | Largest principal angle of the leading score subspaces in specimen space, at or below the limit in (0,90] |
| `pc_extreme_p95_mesh_units` | Maximum matched ±2 SD endpoint distance over the declared PCs, at or below the limit |

Distance units are the declared mesh units. The sampling is the existing
deterministic nearest-vertex proxy, with at most 5,000 vertices per direction;
it is not an exact continuous-surface bound. Score subspace angles are not
feature-space loading angles. PC signs may reverse; endpoint pairs allow this
sign ambiguity. Near-tied axes may rotate, leaving axis-specific endpoint
comparisons inconclusive even when the score subspace is stable.

## Evidence and outcome

The reader verifies the frozen source/config/derived hashes, exact future-run
configuration, design fingerprint, timestamps, ordered cohort and output evidence.
It requires native tolerance and valid geometry for an eligible level. All
comparisons use fitted LDDMM tangent PCA. PC extremes must come from the existing
verified native **Show shape changes along PC axes** operation at ±2 SD.
Missing PC axes or endpoint files are reported with the next action; the study
does not compute them automatically.

Only complete declared evidence can support the smallest tested level meeting
the thresholds. Otherwise the report states that no face-count recommendation
is supported. A numerical recommendation applies to this tested design and
remains separate from anatomical/biological approval and any universal minimum
resolution claim. Protocols, assignments and reports contain private paths and
must be reviewed before sharing.
