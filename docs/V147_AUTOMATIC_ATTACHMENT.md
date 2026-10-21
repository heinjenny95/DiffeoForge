# v147 automatic pilot matching-method comparison

New guided desktop projects default to **Automatic — compare both methods**.
Starting that pilot compares Current and Varifold before further parameter
calibration. The user reviews reconstructions and need not choose a technical
attachment name in advance. Opening, preparing or installing never starts fits.

## Matched trials

The comparison is a separate immutable study. It retains every selected pilot
original, the original aligned template, runtime arithmetic, deformation width,
time integration and native stopping tolerance. Both methods receive the same
explicit control grid, fresh zero-field initialization and three setting pairs:
the declared attachment/noise center, half-width/half-noise and twice-width with
the center noise. Each trial has up to 120 iterations. Native tolerance can stop
earlier. Template and controls are frozen for this comparison. Neither rejected
fields nor old pilot approvals initialize or approve the comparison.

All selected pilot specimens are compared directly, rather than inferring a
winner from a small subset. This costs six multi-specimen trials before review;
the pending pilot and comparison start controls show this workload. Full original
surfaces are scientific inputs. Display proxies never replace them.

## Common evaluation and recommendation

The native Current/Varifold objective values and regularity magnitudes are not
compared as common quality scores. Instead, each reconstruction is measured
against its bound original with two independently seeded, area-stratified sets
of 8,192 probes per direction and point-to-triangle distances. Record global
p95/p99/mean, directional tails in a fixed 4-by-4-by-4 original-coordinate grid,
and the number of probes in each occupied region. Sparse regions retain their
maximum rather than disappearing. Matching original-side regions are compared
individually across candidates. Distances are normalized by each original's
bounding-box diagonal. Original samples and scalar diagnostics have a bounded
content/protocol-bound memory cache; complete meshes are not retained by it.

Area ratio and, only for closed consistently wound surfaces, signed-volume ratio
provide shrinkage diagnostics. Less than 10% of the corresponding original is an
explicit engineering warning. It is not a universal biological acceptance limit,
not a template-volume-preservation penalty and not an anatomical rejection.
Signed-volume reversal is also reported. A warned candidate cannot receive an
automatic recommendation, but its geometric evidence remains part of the
comparison and it remains inspectable.

Choose one settings candidate per method for the whole pilot, preferring
unwarned candidates, then the smallest worst normalized regional/global tail.
Never combine different per-animal winners. Recommend a method only when all
six trials completed, both methods have numerically converged, valid, unrejected
evidence, and one finalist's upper observed error range is no worse than the
other's lower range on every subject/global/original-region statistic, with a
strict improvement somewhere. The normalized arithmetic tie allowance is 1e-6;
it is not an anatomical tolerance or a statistical confidence interval. Overlap,
subject trade-offs, missing evidence or failed trials do not force a winner.
The rule deliberately favors an inconclusive result over an unsupported default.

The UI says **Two methods compared · … recommended** or **No clear advantage**.
Missing usable evidence is reported separately. The best option per method is
shown first, with the recommended option leading; other settings are collapsible.
Individual continuation controls are hidden during the matched comparison so a
one-sided budget change cannot be mistaken for the declared comparison.
Detailed warnings and measurements remain in the saved results. A hash-bound
comparison report records candidate event bindings and explicitly records that
no anatomical approval was granted. The ordinary every-specimen visual review,
provisional-cap selection, integration and final scientific gates still apply.

## Continuing and preserving existing work

After the researcher's reviewed stage selection, the chosen attachment type is
retained for subsequent stages, extensions and the final full-cohort configuration.
The original project's template/control update policy is restored after the
matched comparison. No mixed-method fields are spliced into a PCA. Numerical
completion and anatomical approval remain distinct.

The placeholder Current value in an unresolved automatic configuration cannot be
rendered into executable native XML. Cancel uses the existing active controller
and prevents subsequent candidates. A comparison lock rejects concurrent work.
Saved pointers reopen the comparison; completed trials are reused without another
fit. Changing inputs, controls or immutable study bindings is rejected.

Existing manually selected Current/Varifold projects and saved pilots retain their
original configuration and execution path. There is no automatic migration or
change to existing results. The expert selector still offers explicit Current or
Varifold; Automatic requires guided calibration.

## Verification boundary

Software tests use public synthetic geometry and simulated controller receipts;
they do not execute an optimizer. They cover matched fresh preparation, original
preservation, tamper rejection, neutral objective scaling, subject trade-offs,
sampling overlap, missing/failed evidence, shrinkage, visual rejection, resumption,
cancellation, categorical-choice propagation, native XML guarding and desktop
presentation. An actual point-to-triangle example includes a small missing
component that global p99 misses but the regional diagnostic exposes.

These tests do not establish a universal winning representation, tooth counts,
anatomical correspondence or real-study fit quality. Regional sampling can miss
smaller structures. Three tested settings are a bounded search, not an optimum;
six equal iteration caps do not prove equal numerical accuracy. Native prospective
comparison and independent first use remain open. No private or synthetic native
fit, atlas or PCA run is started as part of this software delivery.

Method background: [Charon and Trouve, 2013](https://arxiv.org/abs/1304.6108).
