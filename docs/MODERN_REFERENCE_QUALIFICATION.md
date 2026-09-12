# Modern Engine fixed-reference qualification

Status: **first real Weevil screening run completed; continuation protocol frozen**.

The first useful Deformetrica comparison does not train two independent atlases
and then ask whether their freely estimated templates happen to look alike. That
would combine template drift, control-grid drift, optimizer behavior, and subject
registration into one hard-to-interpret difference.

DiffeoForge instead freezes a completed, verified Deformetrica result as the
reference:

1. copy the estimated Deformetrica template;
2. copy its exact estimated control points;
3. select subjects without inspecting any Modern result;
   candidates that fail the exact declared Modern mesh-quality gates are recorded
   and skipped before computation, then the deterministic order continues;
4. retain the matching Deformetrica reconstructions;
5. run the Modern Engine with only subject momenta in the optimizer block order;
6. compare both reconstruction sets to the same original surfaces with the same
   deterministic sampled symmetric vertex-to-triangle metric.

Internal objective values are not treated as equivalent across engines. The two
implementations can use different parameterizations and numerical trajectories,
so an equal or lower raw objective would not by itself establish equivalent
registration.

## Prospective commands

Create a no-results-yet design:

```text
diffeoforge modern-reference-qualification-init REFERENCE_RUN --output DESIGN
```

The exact equal query/source tile size remains explicit and defaults to the
established 64-row screening value. A different prospectively justified value
can be frozen with `--tile-size N`; the generated configuration and its hash
record the choice before Modern results exist.

Verify the frozen design without computing:

```text
diffeoforge modern-reference-qualification-verify DESIGN
```

Run the generated Modern configuration through the ordinary immutable workflow:

```text
diffeoforge modern-run DESIGN/modern-fixed-reference.yaml
```

After the Modern run verifies, create an independent assessment:

```text
diffeoforge modern-reference-qualification-assess DESIGN MODERN_RUN --output ASSESSMENT

diffeoforge modern-reference-qualification-assessment-verify ASSESSMENT
```

Both commands accept `--metric-workers 1..8`; the CLI default is four. Subject
metrics are evaluated concurrently, while results are accumulated in the frozen
design order, so worker scheduling cannot change assessment JSON, HTML, hashes,
or gate decisions. The CLI prints one completed-subject event for both the
initial assessment pass and the independent recomputation pass. Direct Python
callers retain the conservative single-worker default unless they opt in.

If the optimizer reaches its declared cycle cap without convergence, freeze a
separate successor rather than altering or restarting the completed run:

```text
diffeoforge modern-reference-qualification-continue DESIGN MODERN_RUN \
  --output CONTINUATION_DESIGN --cycles 10
```

This command verifies the parent design, workflow, and nested bundle; copies
its final momenta; derives each new starter step from the last accepted step;
and SHA-binds the complete lineage. New continuation design v0.4 additionally
records the parent and expected successor engine implementations plus the
parent final objective. Assessment then requires the successor's verified
engine identity and initial objective to match those frozen values. It does not
start the successor optimizer. Existing immutable v0.3 designs remain
verifiable but are not retroactively given evidence they did not record.

New assessment v0.3 artifacts also record the verified optimizer termination,
cycle and line-search counts, final objective components, engine
implementation, optimizer-history hash, and the normalized per-decision
objective/gradient/step trajectory. The report states the objective gain and
whether the observed maximizing trajectory is non-decreasing. These are
provenance and convergence evidence; they do not change any predeclared
registration gate or turn an iteration-cap result into convergence. The
dedicated verifier revalidates the bound design and workflow, recomputes every
external surface metric and trajectory field, and requires regenerated JSON and
HTML to agree with the published assessment. Existing v0.1 and v0.2 assessments
retain their original strict meaning.

## Predeclared engineering gates

The v0.1 design freezes the following provisional gates before Modern results
exist:

- verified Modern workflow and nested bundle;
- explicit Modern optimizer convergence; an iteration-cap result is reported as
  inconclusive rather than as registration non-inferiority;
- pooled external residual p95 no more than 1.20 times the reference value;
- per-subject residual ratio no more than 1.25 for at least 80% of subjects;
- pooled cross-engine reconstruction p95 no more than 5% of the frozen template
  bounding-box diagonal.

These thresholds are engineering non-inferiority criteria for a pilot. They are
not validated universal tolerances, optimizer-equivalence proof, biological
validation, convergence proof, GPU parity, or evidence that the engine is ready
for 300 specimens.

## Full-resolution Weevil evidence frozen on 2026-08-22

The first private design attempted five pre-results geometry-diverse subjects,
approximately 16,652–20,166 triangles per subject, the 18,236-triangle estimated
template, and 100 copied Deformetrica control points. It uses CPU/float64,
64-by-64 exact blockwise evaluation, analytical backward recomputation, and a
three-cycle screening cap. Unless the optimizer reaches its declared gradient
tolerance within that cap, its later comparison is explicitly inconclusive and
must motivate a longer predeclared convergence run rather than a pass/fail claim.

A single-subject, single fresh-process objective-plus-gradient observation took
124.129 seconds with 2.294 GiB sampled peak RSS on the local machine. This one
measurement is a hardware-bound planning observation, not a full-run ETA or a
scaling law.

The first execution attempt stopped before optimizer initialization because one
preselected pilot subject failed the Modern non-manifold-edge and single-component
gates. Design v0.2 therefore performs and records the same quality screening while
the selection remains prospective, replacing an ineligible candidate only with
the next subject in the already declared deterministic order. It never repairs or
silently alters a source mesh.

The screened five-subject run then completed all three declared cycles without
meeting the gradient tolerance, so its engineering decision is
`inconclusive_not_converged`. Its cross-engine reconstruction p95 passed the
provisional 5% diagonal gate (`0.028318`), while its provisional pooled
external-residual ratio was `1.60409`; that ratio is not interpreted as a
pass/fail result because convergence was absent.

Continuation design v0.3 is now frozen for ten further momenta-only cycles. It
starts from the verified parent momenta and the last accepted momenta step
`0.00015625`, rather than zero momenta and the original `0.01` starter. The
successor remains a sequential pilot, not independent validation evidence.

## Engine 0.9 prospective 16-subject result (23 August 2026)

A new initial design was frozen before its Modern result existed and explicitly
bound to Modern Engine implementation `0.9`. It selected 16 full-resolution
Weevil subjects, copied the matching Deformetrica reconstructions, fixed the
estimated template and 100 control points, and declared a momenta-only L-BFGS
run with a 150-cycle cap and relative-objective tolerance `0.0001`.

The immutable Modern workflow completed and verified. Optimization stopped by
the declared relative-objective criterion after 83 cycles rather than by the
cycle cap. All 83 decisions were accepted; the run used 88 line-search
evaluations. The objective increased monotonically from `-612.108853308423` to
`-21.786620266872`, a gain of `590.322233041552`.

The separately generated fixed-reference assessment reports `pass` for every
predeclared engineering gate:

- pooled external residual p95: reference `0.035650977379`, Modern
  `0.027034298906`, ratio `0.758304565363` against the maximum `1.20`;
- per-subject residual-ratio gate: 16/16 subjects passed, fraction `1.0`
  against the minimum `0.80`;
- pooled cross-engine reconstruction p95: `0.017734582040` of the frozen
  template diagonal against the maximum `0.05`;
- verified workflow and explicit optimizer convergence: both true.

The strict assessment verifier independently recomputes all surface-distance
metrics and must reproduce the JSON and HTML byte-for-byte. This result is
prospective engineering non-inferiority evidence for this fixed-reference,
16-subject registration test. It is not proof of atlas equivalence, biological
validity, GPU parity, or readiness for a 300-subject production study.

After the result was frozen, the unchanged strict verifier was run with four
subject workers. It reproduced the published PASS assessment in `210.83 s` on
the local machine, with approximately 460 MiB observed working set. This is a
machine-specific execution observation, not a general runtime promise.
