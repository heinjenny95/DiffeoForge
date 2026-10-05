# v108 — continue a saved numerical resolution comparison

Stage 4 can finish its initial timepoint options without a recommendation when
no converged option agrees with its next finer reference within the prospectively
declared tolerances. The finest tested count has no finer reference of its own.
Previously the dialog offered no targeted way to extend that comparison.

**Test finer resolution (N time points)** now appends one full-cohort option,
ten timepoints above the previous maximum, and executes only that new option in
the background. It reuses the verified finest run's learned template, ordered
momenta and control points. Spatial settings, optimizer settings and declared
criteria stay fixed. Preparation, initialization hashes and source evidence are
recorded before execution; reopening verifies them. Existing configurations,
results, decisions and earlier stage selections are preserved.

The source must be complete, converged, geometrically valid, cover the full
pilot and not be visually rejected. A pending addition must finish before another
can be declared. Legacy studies without prospective tolerances retain their
original meaning. The next-finer reference itself must also be converged and
valid before it can establish stability for a coarser candidate. Neither a visual
approval nor an iteration-limited reference can replace numerical qualification.

If the additional comparison qualifies a candidate, the existing ranking selects
the smallest adequate count. Anatomical QC remains a separate human decision.
If none qualifies, the user can explicitly request the next finer comparison;
the software does not start an unbounded search or change tolerances to produce
a winner. Warm initialization and objective-change stopping do not prove a global
optimum or independent scientific robustness. Earlier provisional choices remain
in the provenance even if a later candidate converges.

80 scoped integration, study, retention, provisional-selection, dialog, version
and Windows contract cases passed. Checks cover append-only history, locked settings and full ordered cohort,
source/configuration tampering, reopening successive additions, no invented QC,
one-option dispatch and refusal of nonconverged finer references. These use
synthetic receipts; the saved private Stage 4 and its actual ordered learned seed
were verified read-only, including full-cohort initialization paths, with the
study journal unchanged. No private optimizer
run is started during development. Packaging and local installation are recorded
separately after verification.
