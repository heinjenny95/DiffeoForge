# v152 — accepted pilot at the screening limit

An accepted individual fit could still require another coverage check after the
shared screening budget was spent on method comparisons and recovery trials.
The green continuation action then failed the budget guard. Its error text was
subsequently replaced by the asynchronous evidence refresh, leaving an apparently
unchanged screen.

The accepted method card now calculates all remaining checks on the same method
and parameter values. When the remaining budget is insufficient, it explains the
exact shortfall and offers an explicit, minimal coverage allowance. That action
prepares only the next single-target trial. Run remains separate; saved fits,
review bindings and existing settings are retained. With complete coverage,
the action explicitly prepares the required joint check.

The allowance is recorded in a successor manifest and bound to its source manifest,
accepted fit and unchanged settings. It cannot be reused for parameter changes,
method searches or a second allowance. A rejected coverage fit requires input or
template review rather than an unbounded search. Existing studies without the new
field retain their original budget checks. A method-pair tie action is hidden when
it would consume the required remaining coverage budget.

Transition/start errors also have a persistent error panel. Background refreshes
and resizing cannot erase them; a new explicit attempt clears the old error.

Synthetic regression tests cover the exhausted saved-study route, minimal
allowance, explicit Run, review persistence, source/settings/withdrawn-review
checks, final joint/time-resolution gates and the actual asynchronous UI action.
No owner/native fit is started. Runtime delivery verification is tracked separately
from source checks; software tests do not establish anatomical validity.
