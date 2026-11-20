# Changed pilot marks retain their own capture evidence

After a useful regional fit, adding a second missing feature could select finer
movement too early. The planner reused the first patch's improvement and pooled
distance even though they had been measured for a different set of marks. A newly
marked feature still outside capture could consequently receive a short-range
detail test.

Regional quality now guides a new proposal only when its recorded marks exactly
match the requested marks, including geometry, purpose, source identity and
symptom. Missing scope is unknown. This applies both to the current result and
to retained quality considered during whole-surface recovery. Changed marks use
their freshly bound capture measurement; the saved field stays available as the
initialization/comparison. Unchanged marks retain the existing measured routes.

This changes future proposal selection. Existing manifests, prepared trials,
fields and reviews are not rewritten. The owner explicitly prepares and runs a
new trial. A broader capture hypothesis is not proof that it will fit anatomy.
Solver equations, tolerances, iteration allowances, precision and review interval
are unchanged; no automatic approval or new scientific computation is introduced.

Verification: the original rule failed six focused changed/unknown-scope cases;
the corrected rule passes those cases, unchanged-scope behavior and a retained-
recovery case. Existing scoped proposal and geometry/continuation checks pass:
101 distinct focused source cases and lint in total.
Older synthetic fixtures now declare the mark scope and retained-singleton
context required by the current production contract. Two saved owner studies
remain loadable; a write/execution-blocked metadata replay preserves the source
field and chooses capture from both marks. It does not run or evaluate a new fit.

Elapsed run duration can include time waiting for a human review. That waiting
is not active fitting time; the ten-minute accepted-state review remains enabled.
Package and installation verification are recorded separately when completed.
