# Atlas initialization and stopping

On the Deformetrica atlas review page, select an initialization and a stopping
rule. A completed pilot can seed either route. **Direct start** skips the
remaining single-specimen fits. **Start from individual fits** runs those fits
on the fixed pilot basis before joint optimization. Both routes preserve the
approved pilot fields. Existing project configurations without a stopping
policy retain their native behavior.

**For morphospace studies, we recommend Morphospace stability.**
This rule tests the quantity used to compare specimens. The cohort distance
matrix must change by less than 1% and each specimen's distance profile by
less than 2% over the required windows. Inspect the reconstructed surfaces
separately to assess anatomical fit.

**Optimizer convergence** offers two presets for the joint atlas. Both use
the GradientAscent test in Deformetrica 4.3. For objective values `F`, the
test is `abs(F[k] - F[k-1]) < tolerance * abs(F[k] - F[0])`.

- **DiffeoForge default (1e-6)** requires a 100-fold smaller relative step
  before stopping. We use this stricter threshold because a single small
  update can occur while the atlas is still changing. It can increase runtime.
- **Deformetrica 4.3 default (1e-4)** reproduces the original optimizer
  threshold. It can stop earlier on the same sequence of updates.

Neither tolerance measures the error at a particular anatomical feature or
the stability of the distances between specimens. Review shows the actual
tolerance saved for the run. A distinct custom project tolerance is also
available. Selecting a joint preset preserves the configured tolerance for
individual initialization fits. Previously prepared runs keep their settings.

## Continue a saved atlas in stages

Choose **Open results…** and select the saved reference atlas. Use **Add
project folder…** if the project is missing from the list. Open the selected
result and choose **Continue from this checkpoint…** in Visual QC or Results
to see its accepted iteration and stop reason. Each new stage takes the saved
template, control points and momenta from that checkpoint. You can keep using
the original run and its exports for downstream analysis.

Keep the original project when exporting meshes or PCA tables. Continuation
reads the atlas run folder, which contains the native optimizer checkpoint.
Older atlas output formats are supported when their saved evidence identifies
the last accepted state unambiguously.
If the line search ended the run early, a verified final export can still
serve as the starting point. A new stage may stop at that same iteration if
the optimizer cannot find another acceptable step.

| Next question | Stopping rule to choose |
| --- | --- |
| Would a stricter numerical fit change my result? | **Optimizer convergence**. Choose a tolerance such as 1e-6 and a total iteration limit above the saved iteration. Either can end this stage. |
| What does the atlas look like at a particular iteration? | **Run to iteration number**. Enter the total iteration you want to reach. A small objective update or stable distance matrix does not end this stage early. |
| Are distances between specimens stable? | **Morphospace stability**. Choose a total iteration limit or select **No joint iteration limit**. |

For example, a researcher can export the atlas that stopped at 1e-4, then
continue it directly to morphospace stability. They can also reopen that same
1e-4 result, choose 1e-6 and compare both branches. Each completed stage with
a verified final joint checkpoint can serve as the source for another stage.
Review the new settings and destination, then choose **Start atlas continuation**.

The total limit includes the saved iterations. Starting at 600 and choosing
850 allows 250 more accepted steps. Cancellation and technical stops such as
an exhausted line search can end any stage sooner. Restoring the model
reinitializes the gradient and line search, so a staged run can follow a
different path from a single uninterrupted run.

Staged numerical continuations carry forward the earliest verified objective
reference available in the chain, including through changes of stopping rule.
For legacy data without a recoverable reference, review identifies the saved
iteration at which the new reference starts. Each new morphospace stage builds
its distance comparisons from the restored checkpoint. Its first full short
window requires 200 new accepted iterations. The quality threshold describes
stability of the measured distances over those windows. The final surface fit
still needs anatomical review.

## How morphospace stopping works

**Morphospace stability · with iteration limit** compares every 25 accepted joint
iterations with the state 200 accepted iterations earlier and, once a full
longer window is available, with the state 400 iterations earlier. Each full
required window must pass both the cohort threshold (strictly below 1%) and
each specimen's profile threshold (strictly below 2%). Single-specimen
initialization steps are excluded. The native GradientAscent stopping test can
trigger without ending automatic mode. The optimizer continues in the same
invocation with its original reference and step-size history. This choice
uses the configured iteration cap.

**Morphospace stability · no iteration limit** uses the same
stability checks with an open-ended joint optimizer loop. The setup must
explicitly select this policy. Individual initialization keeps its declared
budget. Cancellation, numerical and line-search failures, and explicitly
enabled anatomical review pauses retain their behavior. Live progress shows
accepted iteration measurements and observed runtime. Completion time is
unknown until the stopping condition is met. The saved policy persists when
resuming an interrupted open-ended run.

In both morphospace stopping modes, the live display and saved result show
the stability comparisons. At termination, both report their available spans. A partial
comparison cannot satisfy a required full window. Resuming from a saved
checkpoint starts a new comparison history at that checkpoint.

## The +300 shortcut

When the joint atlas reaches its iteration cap,
**Continue +300 iterations** restores the accepted parameters and iteration.
The relative tolerance test uses the exact objective at the start of the
original joint optimization, normally iteration 0. The source report, origin
field checkpoint and final native checkpoint are verified before preparation.
Subsequent capped extensions and interrupted successors carry the same
reference in their protected provenance and checkpoints. For a legacy run
that already restarted its optimizer before this feature, the first extension
preserves the reference of the recorded segment. The desktop shows its origin
iteration before launch. Deformetrica reevaluates the gradient and initializes
its line search from the resumed fit. Final surface export remains enabled.

After a verified native tolerance stop, the
explicit +300 action prepares a new run using the exact saved state and
one-tenth of the source tolerance. The new ceiling is the saved accepted
iteration plus 300. Deformetrica restarts the optimizer and resets its
objective reference, gradient, and line-search step sizes. The successor
records both settings and binds the source checkpoint and log.

## What the run measures

Each checkpoint contributes its own momenta and control points. The same
ordered cohort and deformation kernel define both original-scale LDDMM
distance matrices. The cohort compares the upper triangle and each specimen
compares its own distance profile, omitting the diagonal. The reported
percentage is 100 times the L2 norm of the change divided by the L2 norm of
the earlier vector. Missing, incompatible and zero-baseline fields leave the
assessment unavailable.

The run retains the observations, field checkpoint hashes, the policy, and
the terminal reason alongside the exact accepted native export checkpoint.
The live plot displays the weighted fit error alongside the stability
measurements. The thresholds describe change over a finite observed window.
Visual QC still assesses reconstruction anatomy, and paired saved atlases
support biological sensitivity analysis across initializations.

This workflow uses the pinned Deformetrica 4.3 GradientAscent optimizer for
full-cohort atlases with compact checkpoints and final export. The adapter
checks the native optimizer source identity before binding the accepted-step
and final-export hooks.
