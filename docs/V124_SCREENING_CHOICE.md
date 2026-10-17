# v124 — choose one joint test after early specimen review

After all early screens in stages 2 and 3 have been decided, the desktop shows
their saved numerical measurements and an explicit chooser. There is no default
winner. **Test selected option with all N specimens** runs only that kept option;
it does not turn every earlier visual approval into a joint calculation.

The table sorts the largest sampled p95 across the chosen screening specimens,
shows median distance, regularity, area distortion, resampling sensitivity and
the optimizer stop. Missing or non-finite measurements remain unavailable.
Distances use project coordinates; regularity and distortion do not compensate
for poorer fit. Small sampled differences do not establish a reliable winner.
Frozen-reference singleton evidence cannot predict the optimum joint atlas.

The explicit choice is appended to the parent ledger and bound to the screening
queue and its verified review events. Reopening restores it. The runner enforces
the saved scope even if called without a candidate filter. Other kept options
are deferred, not rejected; their files and anatomical approvals remain intact.
The prior approved joint baseline stays available. No screen momentum field is
promoted into a joint fit. A new joint result requires fresh all-specimen QC and
the existing numerical gates before stage advancement. Cancellation/interruption
cannot dispatch another option; retry stays on the selected joint option.

Existing screening queues need no migration or rerun. Joint comparisons that
already started retain their historical scope and cannot be relabelled as a
single-option test. The source-only legacy runner still supports explicitly
requested batch comparisons when no choice has been saved. Stage 4 is unchanged.

Verification uses synthetic saved studies and fake native controllers: multiple
kept approvals, exact single-candidate dispatch, unchanged screen files/reviews,
reopening, stale-choice rejection, legacy protection, separate joint QC and stage
advancement, desktop selection and worker routing. These are software checks,
not anatomical validation, a private fit rerun or a universal ranking claim.
Installer and installed states are recorded separately from source completion.
