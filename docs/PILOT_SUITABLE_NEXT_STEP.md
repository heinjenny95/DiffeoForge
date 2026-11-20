# Continue after approving a protected local fit

The pilot saved suitable-fit decisions but provided no continuation for approved
regional fits: its UI hid the ordinary Confirm action and exposed only optional
refinement. Local acceptance was correctly separated from common-atlas approval,
but the absence of an actionable transition left the owner in a review loop.

dev171 adds **Use suitable fit → prepare atlas-model check** immediately before
the inspection/recovery controls. It prepares one separate standard-objective
check on the same form, initialized from the complete verified local momentum
field. Run remains explicit. The local result and its approval stay intact;
copying a field does not approve the standard objective or another specimen.

The new marker binds the accepted source, original template/control basis,
precision and integration settings. A source with an inseparable residual prefix
is rejected with an actionable explanation; it is never replaced by a fresh
zero start. The shared check uses the existing ordinary cohort optimizer and its
standard objective, retaining the accepted field as initialization. Its initial
allowance is the existing 120-iteration pilot screen, rather than inheriting a
long regional refinement allowance. This is a new objective/optimizer history,
not an uninterrupted continuation of the local optimization.

After review of this new standard-objective result, ordinary coverage can proceed
to the remaining forms and then joint confirmation. The numerical model is kept
consistent throughout. Earlier approvals on another time grid do not count as
coverage of this model. The approved local fit remains an inspectable comparison;
there is no transfer of its regional constraints or approval to the common model,
no old PCA update, and no automatic launch from merely saving or rendering review.
The common model may change the fit and must be reviewed in its own right.

Verification uses synthetic receipt/controller journeys through the new check,
remaining forms and joint preparation, exact nonzero field copying, 10- and
37-point numerical propagation, new-review requirements, residual rejection and
UI action dispatch. A new tiny public native regional fit supplied finite momenta
to a standard native check with two identical public fixture targets; both returned
zero, retained Float32/37-point RK2 and left the source unchanged. This native
engineering check is not prospective anatomical, cohort-quality or speed evidence.
The reported owner fit was inspected under a write/execution-denying audit, with
no owner fit started. Packaging and installation are recorded separately.
