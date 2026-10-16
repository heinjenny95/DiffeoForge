# v126 — control-point density of the chosen joint fit

The existing pilot varies deformation reach and initial point spacing together.
Its single-option joint confirmation therefore cannot independently establish
adequate control density. A completed or final-stage reviewed pilot now offers
**Compare control-point density of chosen fit** without repeating its earlier
parameter screens or replacing its results and anatomical decisions.

## Separate, bounded comparison

The action prepares or reopens a sibling study; preparation starts no engine.
It binds the chosen source result, current approval, cohort order, configuration,
learned template, common controls and momenta. The source study remains unchanged.
Withdrawn source approval, changed output bindings, settings, inputs, momenta or
controls block reuse. A failed preparation is retained for diagnosis, never
silently overwritten or deleted.

Three explicit joint fits use the same pilot cohort:

1. A matched continuation reference with the original learned common basis.
2. A nested basis with 1.5 times the original point count, rounded up.
3. A nested basis with twice the original point count.

Original control coordinates and ordered pilot momentum rows are retained in
every starting basis. New points are selected deterministically by farthest-first
coverage from bounding-box lattices at 0.8 and two-thirds of the source spacing,
excluding near-coincident points. The second addition retains the first. Extra
momentum vectors start at zero, so the initial deformation field is analytically
unchanged; bit-identical floating-point trajectories are not claimed. These are
explicit supplied control files, not an assertion that the learned basis remains
a regular lattice. Initial spacing in the configuration describes the candidate
lattice, while the actual bound point count is recorded and shown separately.

Attachment/deformation kernel widths, noise, timepoints, full-resolution pilot
targets, runtime, optimizer tolerance/cap and freeze settings remain unchanged.
All variants start from the same learned template and deformation. The matched
reference separates density changes from additional optimization. Earlier A–E
choices are not replayed, and independent specimen fits are not spliced together.

## Review, comparison and selection

Each launch fits one explicitly ordered variant, then pauses for fresh anatomical
review. A direct runner call cannot batch or skip variants or bypass an outstanding
review. New fits never inherit the source's anatomical approval. The original
approved fit remains available through **Return to original approved fit**; the
comparison is saved and can be reopened without restarting completed variants.

The comparison shows actual point counts, the worst specimen's sampled surface
p95 normalized by its original bounding-box diagonal, and normalized endpoint
change against the matched reference. All-subject fit/endpoint measurements,
optimizer stop and runtime are recorded. Surface-fit measurements use the same
area-stratified bidirectional point-to-triangle method as the current fit-search
route. Raw momenta from different bases are not treated as comparable shape-space
coordinates, and no universal accuracy or density threshold is introduced.

After all three fits have been reviewed, the researcher explicitly chooses a
result. The selected state still requires its own fixed-state integration check
and the ordinary convergence or acknowledged provisional-completion gate. Passing
these gates does not automatically rank densities. The JSON/HTML report retains
the source identity, protocol, comparisons and decisions. Full-cohort handoff uses
the selected result's learned template/control basis and the existing ordered
momentum-initialization policy; it neither starts nor approves the full atlas.

## Verification boundaries

Regression coverage includes immutable original approvals/results, unchanged
settings, nested bases and zero extensions, preservation of a nonzero initial
field, stale inputs/settings and source withdrawal, one-fit dispatch, review
pauses, manual selection, integration, reporting, reopening and selected-basis
handoff. Desktop dispatch probes capture workers without executing them.
Private source inspection and packaging/install evidence are recorded separately.

These are software and provenance checks. A finite density comparison is
sensitivity evidence, not a proof of the optimal count, biological validity,
optimizer-global optimality or shape-space stability. Native scientific first-use
acceptance remains separate; no private optimizer job is launched by development
or installation. The separately deployed institutional-server run is unchanged.
