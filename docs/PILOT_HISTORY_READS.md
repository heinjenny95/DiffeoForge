# Bounded retained-history verification

A pilot view can inspect context, common-model approvals, retained working fits
and next-form proposals from the same history. Previously only context collection
shared ancestor verification; subsequent parts could rebuild the same long
lineage repeatedly. Resolving a retained run could repeat nested verification
again, including immediately before keeping an already approved joint result.

The complete read-only state view, retained-reference check and run-resolution
walk now share one existing verification scope. Retained records also have an
operation-local cache keyed by the complete record and current study path.
Returning a cached candidate uses a deep copy. In-progress entries reject cycles.

Every cache hit checks the manifest/input witnesses and the retained evidence
witnesses: event and visual-review journals, candidate configuration, run
manifest/result/inventory and retained evidence. An absent optional journal is
also witnessed, so creating one during the read cannot go unnoticed. Nothing
survives the end of the read action. A new Run, decision or later view performs
fresh verification; writes stay outside the read scope.

Controlled cases count full ancestor checks across the complete state view and
multi-stage retained run resolution, then require new checks on the next call.
Mutation cases cover inputs, ancestor assets, journals, newly created visual
reviews, configs, outputs and caller-owned returned metrics. Ordinary withdrawal,
same-output retention and end-to-end completion tests remain required. No new
optimizer, anatomical approval or scientific parameter is introduced.
