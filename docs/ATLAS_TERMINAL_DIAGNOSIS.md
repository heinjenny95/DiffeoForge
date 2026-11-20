# Diagnose a completed Deformetrica atlas

A normally completed GradientAscent run can show **Native stop** in the Run,
Visual QC and Results views. The diagnosis reads the saved manifest, terminal
event, result, native log and matching convergence CSV. The same evidence is
checked when the saved run is reopened. The scan never prepares a new run.

The 10- and 50-iteration windows end at the last logged observation. Deformetrica
4.3 tests the tolerance before printing the accepted step that triggers the
stop. The windows therefore describe recent logged progress and cannot recover
the exact terminal objective or effective stop threshold. Disjoint histories,
sparse observations and printed precision limit the comparison. The reported
change uses the two logged endpoints and their decimal rounding bounds. Its
percentage is relative to the magnitude at the start of **that window**.

The total objective includes both attachment and deformation regularity.
Weighted fit error is the opposite of the logged attachment term. A total
objective gain can accompany a worsening weighted error. Use Visual QC to
assess anatomy and compare saved atlases on the same specimens to assess
biological stability. The diagnostics add no acceptance or rejection rule.

## Explicit continuation after a tolerance stop

The existing +300 action remains available through its verified iteration-limit
route. Its budget is based on the previous configured cap. After a tolerance
stop, much of that cap can be unused. Using that rule for a tolerance-stopped
fit could exceed the intended incremental allowance. A higher cap alone also
does not change the native tolerance criterion.

A later tolerance-stop continuation would need an explicit review and start
action with its own versioned provenance. It can reuse the lifecycle, backend,
protected-input, output-inventory and checkpoint checks from
`inspect_resume_source()`. It must establish the accepted checkpoint iteration
from bound native evidence. Compute the successor cap as that iteration plus
the approved extra budget. The last printed iteration is insufficient.

The review should show the exact checkpoint, extra budget, previous and new
tolerances, and objective-reference policy. An ordinary native resume loads
parameters and the iteration while recomputing its objective reference,
gradient and line-search steps. A preserved reference requires an unrounded
native value and its origin checkpoint binding. The existing preserved-reference
contract covers the same tolerance. Combining a different tolerance with a
preserved reference would need its own verified contract.

The successor must get its own directory and protected receipt linking its
source and checkpoint hashes, accepted iteration, approved budget, effective
optimizer settings and reference policy. It needs its own QC. No tolerance-stop
continuation is implemented by this diagnosis.
