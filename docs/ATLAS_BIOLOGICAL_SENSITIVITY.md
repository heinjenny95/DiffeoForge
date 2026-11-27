# Comparing anatomical findings across atlas variants

The comparison starts from two completed atlas runs with saved, verified PCA results.
In Results, choose **Compare group effects across atlases**, select the second run and
a specimen CSV, and choose the ID column, grouping column, and two levels. Use the
same specimen identifiers in both saved PCAs and in the CSV. The analysis keeps the
model settings and saved fits intact and creates a separate local report.

The table reports the between-group sum of squares as a fraction of total variation
among the selected groups, in the full numerical rank and in PC1–PC2. It includes the
fraction of the squared centroid gap visible in those two PCs. Distance-rank
correlations use all paired specimens. The report highlights the specimens with the largest changes in distance rank. Each atlas retains its stored score metric.
Named coordinate columns can belong to different control-point positions. File-byte
agreement for the staged specimen surfaces, when available, is reported alongside
the exact ID pairing.

The report also compares mean reconstructed vertex displacements when both
Deformetrica runs have the same verified starting template and ordered reconstruction
connectivity. It scales both displacements by the common starting-template diagonal
and weights the RMS and direction cosine by triangle area. The template projections
show example vertices from each variant's largest effects, and the JSON report
records the exact source manifest hashes and overlap. The point tracing view uses a
selected starting-template vertex and shows its two model endpoints over the exact
same aligned specimen surface. Independent anatomical annotations can assess
whether either endpoint is anatomically meaningful. Enter one independent XYZ landmark in the verified aligned frame to measure both endpoint distances to that point.

## Pilot review

In a joint pilot review with an approved individual fit ledger, **Compare with
approved individual fit** opens both verified overlays for the selected specimen.
Measurements on the same original-space marks report both distance directions.
Sampling uncertainty or missing coverage stays visible. The review leaves human
approval with the researcher.

Two plausible saved individual fits can each be closer in a different region.
The pilot can open both areas in linked views and point the researcher to the
trade-off. A marked concern about an opening or connection can instead open the
saved input overlay to inspect the template and specimen before another
optimization. The pilot treats these routes as inspection or bounded experiments.
Before the full atlas, the reviewed pilot setup can prepare a separate small
fixed-template check using distinct surfaces outside the verified pilot history.
The new check uses the saved control points and the declared settings with a
short iteration cap. The prepared diagnostic is separate from the long atlas.
Validation Lab can inspect sealed fixed-template reconstructions for its reserved
subjects. In Step 5 the selected completed specimen can be screened in both
surface-distance directions. These markers indicate where to look. Researchers
still decide whether the anatomical features hold.

## Known local deformation benchmark

Run `python -m diffeoforge.analysis.known_shape_signal create --help` to prepare
copies of one triangular VTK with predeclared local offsets and at least two zero
controls. All copies share ordered topology. The compact smooth displacement has
a bounded amplitude relative to the chosen radius. Record where and why the region
was chosen before looking at any output. For different anatomies repeat on
independent source surfaces.

Use `specimens/subject-*.vtk` and the generated `template.vtk` as the run inputs.
Keep their coordinate frame and hashes. After each completed native atlas, run
`python -m diffeoforge.analysis.known_shape_signal evaluate STUDY RUN`.
The evaluator binds the frozen cohort, starting template and output inventory.
It measures the recovered local displacement projected on the known field,
the fraction of each dose recovered, the outside-region RMS difference, and
the response of the controls against the other zero-dose specimens. Small
end-to-end tests test the calculation and the real backend path.

## Prospective Figure 3 study

Compare stock Deformetrica settings, manual calibration, and the interactive pilot
on the same backend, source geometry, and hardware. Predeclare equally bounded
compute budgets, the calibration protocol, and the scientific endpoints. Record
setup time, hands-on decisions, optimizer effort, and completion including stalled
and abstaining cases. Have independent researchers without LDDMM experience use
the guided workflow. Counterbalance workflow and dataset order to reduce learning
effects. Use independent expert ratings and landmarks chosen before fitting,
with the reviewers blinded to the workflow. Keep the published group labels or
phenotype outcomes outside tuning.

Test whether the participant reaches a usable fit and whether the shared atlas
preserves independent anatomical features on specimens excluded from calibration.
For the known-dose experiment, compare local recovery across anatomies and doses
alongside false signal in controls and displacement outside the intended region.
Report the uncertainty and number of failures with each result. Review examples and
engineering tests establish the software behavior. Participant outcomes and
independent anatomy measurements require the prospective study.