# Pilot continuation effort in atlas iteration budgets

New atlas configurations count completed native checkpoint continuations of
the selected pilot when recommending a starting iteration allowance. Keeping an
earlier suitable field no longer hides that family's later measured effort.
Budget evidence does not select the continuation's field or change any review.

Previously, the budget matched only literal selected candidate IDs. A retained
candidate could therefore select the earlier field while its completed
checkpoint continuation appeared under another ID and contributed no effort.

## Matching evidence

The finalizer uses the verified study journal. A continuation must belong to
the declared native checkpoint protocol and connect to the selected candidate
through matching source/completion events. Its cumulative counters, checkpoint
metadata, completed state, valid geometry and native stop reason must agree.
Repeated continuations follow the chain; earlier cumulative totals are not
added again.

Different parameter candidates, failed or pending attempts, explicitly rejected
branches, unknown/failed stops, stale attempts and inconsistent source links do
not contribute. A completed continuation can contribute effort without having
been adopted as an anatomical result. Existing verification of native resume
settings still applies; the budget collector does not authorize parameter or
geometry changes.

The numerical recommendation rule is unchanged. It retains a higher declared
allowance, allows 1.5 times the observed iterations, adds a 300-step margin when
an observed fit used at least 90% of its cap, and rounds upward to hundreds.
The existing automatic recommendation ceiling remains unchanged.

Illustrative cumulative counters with an earlier 120-step capped pilot:

| Additional evidence | Suggested starting allowance |
|---|---:|
| No matching continuation | 500 |
| Matching continuation finishes at cap 420 | 800 |
| Its next continuation finishes at cap 720 | 1,100 |

An early tolerance stop uses its observed count, not the unused allowance.
These are starting budgets, not predictions of convergence, suitable anatomy,
or runtime. More controls do not by themselves determine an iteration count.
No native tolerance, integration setting, solver equation or fitted field is
changed by this correction.

## Serialization and existing work

Version 2 budget provenance records the included continuation links and their
source/completion event hashes. The selected fit IDs and approvals stay intact.
The resulting allowance reaches both the full-cohort optimizer and its
independent fixed-basis initializers, including the emitted native XML/adapter.
The existing configuration editor shows the same value and identifies the
observed continuation effort.

Existing completed studies and prepared or running atlases retain their saved
configuration. Their version 1 budget remains readable and is not rewritten.
If finishing was interrupted after writing a valid version 1 configuration,
retry preserves that exact legacy contract. This compatibility path accepts
only the complete expected legacy configuration; other edits are still rejected.

## Verification boundary

Tests cover the retained-field continuation case, repeated cumulative resumes,
exclusions, early stopping and higher manual allowances. Journal-based finish,
reopen and preparation journeys verify the native XML and initializer allowance,
unchanged source results/reviews, legacy finish retry and changed-config refusal.
The focused budget, continuation, completion, retention and atlas-handoff group
passed 80 software cases using synthetic execution rather than scientific jobs.
Private read-only replay on existing pilot evidence is kept outside this public
repository. Software serialization qualification does not establish convergence
or anatomical suitability. A new installed runtime is required to use version 2
provenance; a running atlas is never upgraded in place.
