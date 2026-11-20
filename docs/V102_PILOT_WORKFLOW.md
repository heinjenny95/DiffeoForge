# v102 — recoverable pilot review

The pilot could retain a busy controller after an unexpected background
exception, leaving both cancel and close blocked after the calculation had
ended. v102 reports all ordinary worker exceptions and always emits a terminal
notification. Only the worker that owns the controller can release it; a delayed
notification cannot release a newer calculation. Close still protects an active
job. Empty candidate selections produce an actionable error or select the sole
completed individual attempt.

## Review and fallback

- **Maybe / Plan B → try next** keeps the current individual fit and tests the
  next settings for that specimen. It records neither approval nor rejection.
- **Compare Plan B** opens a read-only comparison with the current reconstruction.
- **Review / use Plan B** returns to the exact saved fit without computing or
  deleting later attempts. A new explicit visual review is required before use.
- Fallbacks bind the specimen, series, template/control basis, study and run
  hashes. They cannot transfer across an incompatible common model. The saved
  fallback survives a failure to prepare the next attempt.
- A prominent count uses persisted approvals in the current series. Individual
  fitting no longer displays the unrelated four-stage parameter heading. The
  later combined confirmation has its own all-specimen QC requirement.
- Reopening a rejected option starts a fresh decision form. Historical recorded
  decisions remain in the journal; merely reopening is never a new approval.

Existing studies remain immutable. The exact cause of the reported native hang
was not established from a traceback; exception-injection tests cover the
previously unreported exit paths. This is not a scientific fit-success claim.

## Clearer results and shorter text

Alignment status now gives the next action. Fingerprints, scale ranges,
sensitivity and convergence reports remain in collapsed details. The pilot
shows its actual data context and separates review, optional improvement and
use of an approved option. Changing a selection does not authorize a fit.

**Shape changes along PC axes** appears directly beside the morphospace plots.
Verified saved mean and ±2 SD meshes can be viewed again without shooting them
again. New shooting remains an explicit action and uses the verified source
runtime, estimated template, ordered control points and integration settings.

The reference default is described as **LDDMM-metric tangent-space PCA
(linearized PGA)**. This is a tangent approximation, not exact nonlinear PGA
or proof of an intrinsic mean. Cartesian PCA and generic RBF KernelPCA retain
their own names. Numerical method identifiers, scores, frozen manifests and
historical reports remain unchanged; desktop labels and newly generated methods
text provide the explanation. Historical exports are not rewritten merely to
change terminology.

References: [Vaillant et al. (2004)](https://doi.org/10.1016/j.neuroimage.2004.07.023)
and [Fletcher et al. (2004)](https://doi.org/10.1109/TMI.2004.831793).

## Verification and limits

- 41 lifecycle, sequence, continuation and review regressions passed.
- 99 PCA, metric, endpoint, metadata and methods-report checks passed.
- 92 desktop/activity/project-checkpoint checks passed initially. Two failures
  were corrected: anatomy-neutral wording, and a pre-existing test that omitted
  the explicit deep-validation action introduced in v93. A final 15-case set
  covers these, version identity and the additional fallback/viewer/serializer
  cases. These suites overlap; counts are not an aggregate.
- Endpoint projection independently recovers the declared mean and ±2 SD scores
  in Cartesian and LDDMM-metric coordinates. Unsupported method identities,
  non-finite fields and empty serialized tensors fail before writing.
- Actual Deformetrica 4.3.0 reader round-trip preserved all synthetic values:
  header `1 5 3` returns `(5, 3)`, while `7 5 3` returns `(7, 5, 3)`. The existing
  run-local singleton atlas adapter remains separate from this format check.
- Public synthetic 408,320-face/21.3 MB preview preparation: approximately 0.91 s
  cold, 0.013 s memory reuse and 0.016 s disk reuse on the development host.
  This checks the existing source-bound cache; it excludes native paint,
  full-resolution loading and private-data/first-use acceptance.
- Ruff and compilation checks passed. No private optimizer, atlas or parameter
  tuning was run. Saved scientific approvals remain human decisions.

Independent first-use review, interactive Windows focus behavior and prospective
anatomical acceptance remain open. Installation evidence is recorded separately.
Drive distribution remains request-only.
