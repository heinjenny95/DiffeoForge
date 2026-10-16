# v125 — preserve the selected saved fit when entering Stage 4

A pilot can enter Stage 4 with status `ready`: the selected previous-stage fit
is retained, while the historical time-grid refit options remain unexecuted.
Previously the desktop rebuilt its saved-fit chooser only for `awaiting_review`.
The hidden chooser could therefore still contain a stage-three candidate ID;
the fixed-state check rejected that ID despite displaying an approved retained
fit. Reopening could leave the chooser empty instead.

The desktop now rebuilds the Stage 4 chooser in both states. It removes stale
IDs, preserves a current-stage selection across redraws, and otherwise selects
the latest completed result that has not been rejected. Both primary actions
dispatch the current saved-fit identity. An explicit out-of-stage source is
rejected before any worker is scheduled. A retained Stage 4 card and chooser
say **Saved fit from stage 3**, instead of assigning a misleading new option
letter to unchanged geometry.

This changes desktop selection and labeling only. Existing event ledgers,
screening decisions, anatomical reviews, configuration and native outputs need
no migration or rerun. The default check remains fixed-state Shooting with no
optimization. Numerical integration, native convergence, anatomy and provisional
completion remain separate gates; source approval withdrawal still blocks reuse.

Regression checks reproduce the ready-state transition and stale previous-stage
selection, verify both button routes, retain multiple-current-fit selections,
and protect review/event bytes. They use synthetic studies and captured workers;
dispatch checks do not execute a private fit or establish numerical qualification.
Packaged, installed and distribution evidence are recorded separately from source.
