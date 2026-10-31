# v162 regional continuation from a verified accepted field

The guided pilot retains the user's marked areas and earlier preferred fits.
For a newly guarded regional trial that reached its iteration cap with an
improving finite objective, it can propose more optimization of the same field.
It preserves the original control-point basis, regional objective, protection
terms and preceding field chain. It does not start a different deformation merely
because the first allowance ended. Preparation and execution remain separate
user actions.

Continuation requires a completed, inspected trial, unchanged markings and
objective, no severe preservation regression, and a finite accepted state bound
to the exported parameters. The native checkpoint is read through a restricted
parameter-only reader; it is not a saved SciPy optimization history. Each explicit
successor starts a new optimizer history from those parameters. Failed,
non-finite, uninspected or changed starting evidence is not silently resumed.
Historical unguarded runs keep their previous interpretation.

A native callback cap can return normally without producing an OptimizeResult.
The adapter records that normal return honestly and binds it to the accepted
evaluation and configured cap. It does not invent a final-result event or report
convergence. Explicit native stop evidence and completed return code zero remain
necessary for a cap continuation.

## Precision and responsiveness

Regional evaluation of new guarded runs uses the protected original control-point
input. Native text exports round those coordinates; reusing that rounded export
would change the evaluated field. The loader verifies original coordinate bits,
row order and the finite accepted export. This regional-only choice leaves common
atlas/PCA and historical loaders unchanged.

New regional configurations use at least 37 RK2 timepoints. Higher requested grids
remain higher; existing prepared runs render unchanged, and a same-objective
continuation keeps its exact preceding grid. This is a numerical-resolution
choice, separate from the surface objective and physical fitting settings.

The improvement menu prepares one immutable continuation preview per verified
input operation. It does not repeatedly parse and verify the same field for every
menu alternative. Fresh execution/preparation checks still verify the saved
source and current markings.

## Visual suitability and remaining scope

Users decide whether the overall shape and relevant projections or other local
features are reproduced well enough for their analysis. No anatomy-specific
tooth count or feature detector is hard-coded. Saving **Suitable fit** keeps that
decision and presents inspection/close; further refinement is optional. Numerical
convergence and mesh warnings retain their own meaning.

Controlled native tests exercise the actual generated adapter, CLI, completed
report and output inventory. A separate real-form search used new optimization,
with an independent saved reference used only for assessment. This establishes
neither universal fit quality nor independent-cohort validation. Regional terms
remain specimen-specific: a visually suitable regional fit does not approve a
shared atlas objective or supply independently fitted fields to PCA.
