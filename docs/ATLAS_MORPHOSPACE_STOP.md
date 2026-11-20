# Atlas initialization and stopping

On the Deformetrica atlas review page, select an initialization and a stopping
rule. A completed pilot can seed either route. **Direct start** skips the
remaining single-specimen fits. **Start from individual fits** runs those fits
on the fixed pilot basis before joint optimization. Both routes preserve the
approved pilot fields. Existing project configurations without a stopping
policy retain their native behavior.

**Stop at optimizer convergence and review** keeps the Deformetrica stop and
shows the final accepted joint state. A short available comparison window is
shown with its actual length. After a verified native tolerance stop, the
explicit +300 action prepares a new run using the exact saved state and
one-tenth of the source tolerance. The new ceiling is the saved accepted
iteration plus 300. Deformetrica restarts the optimizer and resets its
objective reference, gradient, and line-search step sizes. The successor
records both settings and binds the source checkpoint and log.

**Run until morphospace stabilizes** compares every 25 accepted joint
iterations with the state 200 accepted iterations earlier and, once a full
longer window is available, with the state 400 iterations earlier. Each full
required window must pass both the cohort threshold (strictly below 1%) and
each specimen's profile threshold (strictly below 2%). Single-specimen
initialization steps are excluded. The native GradientAscent stopping test can
trigger without ending automatic mode. The optimizer continues in the same
invocation with its original reference and step-size history. This choice
uses the configured iteration cap.

**Run until morphospace stabilizes · no iteration limit** uses the same
stability checks with an open-ended joint optimizer loop. The setup must
explicitly select this policy. Individual initialization keeps its declared
budget. Cancellation, numerical and line-search failures, and explicitly
enabled anatomical review pauses retain their behavior. Live progress shows
accepted iteration measurements and observed runtime. Completion time is
unknown until the stopping condition is met. The saved policy persists when
resuming an interrupted open-ended run.

At termination, both comparisons report their available spans. A partial
comparison cannot satisfy a required full window. Resuming from a saved
checkpoint starts a new comparison history at that checkpoint.

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
