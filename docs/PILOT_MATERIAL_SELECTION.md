# Movable material must exclude Retain areas

New regional objectives exclude every triangle incident on a marked fixed
material vertex from the movable focus surface. Previously, an absent feature
could trigger a spherical nearest-source fallback that included the retained
neighbouring projection. This created conflicting instructions even when the
problem and Retain marks were separate.

An absent surface now receives a connected free-source proposal, grown by edge
distance from the nearest eligible face until its area covers the marked target
patch. The plan records the exact source face ids, patch areas and inferred-mark
indices. This is a geometric proposal, not an anatomical correspondence. An
insufficient free component, unavailable surface or conflicting shape guide
produces an actionable area/starting-fit error. No retained part is silently
substituted. All requested problem marks remain in the objective and evaluation.
The proposed source vertices are excluded from automatic outside anchors;
explicit Retain constraints remain independent and unchanged.

New zero-initialized residual bases also cover the actual focus-source vertices,
which can lie outside the target-centred brush. Existing controls are retained;
occupied material voxels are added at the declared spacing, with the same
movement kernel and control budget. Exceeding the budget fails explicitly rather
than silently coarsening the field. Warm and same-objective bases are unchanged.

Public separated-surface tests exercise retained-neighbour exclusion, insufficient
connected material, conflicting guides, support coverage and budget failure. The
regional objective/search suite and continuation/resolution/reference suites pass
128 cases, including four new cases. A
private read-only check reproduces the exact 509-face source proposal and
814-control coordinates of the isolated capture diagnostic. For all three actual
problem marks, no selected triangle touches the fixed patch. All 47 protected
original evidence files remain hash-identical.

This repair does not establish a successful automatic fit for the difficult
specimen. The isolated capture improved the missing projection but failed strict
full-field preservation/time-resolution qualification. Its experimental
coordinate conditioning and capture settings are not adopted by this change.
Native mathematical code, iteration/time budgets, accuracy bounds and approval
requirements are unchanged. Saved plans, fields, journals and owner runs are not
rewritten. Installed runtime remains dev175 until a verified delivery.
