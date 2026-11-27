# Finer time checks also recheck spatial resolution

The saved deformation can need finer numerical evaluation even when no further
optimization is appropriate. The bounded RK2 qualification ladder now extends to
1153 evaluation time points. The normalized temporal tolerance remains 1e-4;
optimizer iterations, convergence tolerance and active review budgets are
unchanged. A field still unresolved at this limit remains unqualified.

When a temporal correction follows spatial refinement, the new time grid is now
checked for additional spatial curvature. Any further conforming original-source
refinement is carried out on the unchanged field, then the coarser comparison is
evaluated on that same final material grid. An older spatial receipt is not copied
over a new endpoint. Existing vertex/triangle and refinement-pass budgets remain.
Retain, automatic outside-reference and final geometry checks use the resulting
common grid and resolution. No fitted coefficients or source surface are changed.

Verification: 34 targeted frame/numerical-policy cases pass, including four new
cases for the extended ladder, unresolved-bound failure and repeated spatial
rechecking/reference binding. Lint passes. An independent private fixed-field
check resolved a previously rejected 577-point evaluation at 1153 points without
optimizer updates: temporal, spatial, full Retain, outside and intersection guards
passed at their unchanged bounds. Protected original evidence remained unchanged.
Anatomical approval is separate; this is not an optimizer convergence claim.

Historical qualification receipts remain sealed and keep their original limits.
Installed runtime remains dev175 until a verified successor is delivered.
