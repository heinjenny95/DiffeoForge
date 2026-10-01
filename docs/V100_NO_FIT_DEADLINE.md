# v100 fit search without a wall-clock deadline

The guided Find fit sequence now runs the current attempt to optimizer completion,
its iteration cap or explicit user cancellation. There is no elapsed-time deadline
or minute selector. One specimen and one attempt still precede human feedback:
rejection starts the next untried settings for that specimen; approval starts the
next specimen. Existing parameters, working geometry and numerical ranking are
unchanged. Removing a deadline does not guarantee convergence or anatomical fit.

Saved v98/v99 sequences open and resume directly, including those with an
exhausted or crash-reserved fit-search-budget.json. Old minute metadata and budget
files remain unchanged as historical evidence. Their directory binding still
identifies the exact study series and serializes execution; it no longer governs
runtime. No migration rewrites immutable manifests, resets reviews or launches
a scientific run. New searches omit minute metadata and budget files.

Finite parameter alternatives, iteration limits, manual cancellation, concurrent
execution locks and supervised native helper failure/hang handling remain.
After all individual approvals, a new shared-template original-target fit and
fresh whole-pilot QC are still required. Individual approvals do not become
scientific approval of a joint atlas.

Compatibility regressions cover an exhausted legacy budget, unchanged original
manifests/checkpoints/reviews, retained approved fits and attempt counts, GUI
reopening/advancement without the minute control, no scheduled deadline, manual
cancellation and exception lock cleanup. Existing rejection, longer-fit, common
basis, original-target joint confirmation, preview QC and version contracts are
also checked. Tests use public synthetic fixtures; no private fitting calculation
is used for this software update. Build and local installation are recorded
separately. The last verified Drive package remains v98 under the on-request policy.
