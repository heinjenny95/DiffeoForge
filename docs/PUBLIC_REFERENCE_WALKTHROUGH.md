# A small, public Reference workflow

Use this example to learn or review DiffeoForge without private research data.
It is six artificial surfaces: one template and five subjects, each with 162
vertices and 320 triangular faces. Units are arbitrary (`unitless`); the meshes
and four-point landmark table are CC0. They have no biological interpretation.

## Before starting

Use a versioned source checkout or a separately authorized desktop build and
record its version/commit. Deformetrica Reference must be configured and verified
in the app first. On Windows, use the managed Reference environment; desktop
installation and backend readiness are different checks. This guide does not
authorize an experimental installer or claim native macOS/Linux release support.

Choose an empty, writable **local** project directory outside the source dataset.
Keep the whole resulting project/run tree together when making a backup.

## Seven steps

1. **New project:** keep **Deformetrica Reference** selected. Mesh folder:
   `examples/synthetic/meshes`; template: `template.vtk`; subjects:
   `subject-*.vtk` (five, not six). Choose `unitless`.
2. **Alignment:** select `examples/synthetic/landmarks.csv`. It provides four
   corresponding generator vertices (`a`-`d`) for every mesh. Choose **Shape only
   — surface scale, resolution-independent**, keep reflection off, preview GPA,
   inspect the overlay and approve only after reviewing it. Do not rescale or
   mirror the input files manually. Raw inputs remain unchanged.
3. **Starting parameters:** use balanced detail/deformation preferences. These
   define an exploratory search, not known correct parameters. For this small
   exercise, select three pilot subjects, four CPU threads where available and
   a 100-iteration cap; record any different settings. A cap is not convergence.
4. **Pilot:** start the calibration manually, or choose AFK automatic provisional
   selection. On return, read the selected values and uncertainty/search-boundary
   warnings. AFK neither visually approves registrations nor starts the final atlas
   on the user's behalf. If it pauses or fails, preserve the study and review the
   stated reason; do not start a duplicate study merely because the UI is busy.
5. **Atlas:** after deciding whether the calibrated settings are defensible for
   this engineering exercise, explicitly launch the selected atlas configuration.
   Keep the run ID, resolved configuration, engine version, logs and manifest.
6. **Visual QC:** review the flagged reconstructions against their targets, rotate
   them and inspect original detail when needed. Save the actual judgement and
   any note. An implausible registration must not be converted to an approval to
   advance. Use the documented revise/rerun path; no flags is not a guarantee.
7. **Comparison/export:** after the required QC decisions, select the shape-space
   methods. The default uses the fitted LDDMM deformation-kernel metric; RBF kPCA,
   Isomap and diffusion maps are distinct sensitivity views. Inspect the method
   report and retain the project-folder PDF with its provenance sidecars and
   the original comparison bundle. Different methods' spectral percentages are
   not interchangeable, and similar plots do not establish biological validity.

Validation Lab is optional. It tests the declared nearby kernel/control-point
alternatives with noise fixed; it does not certify a universally optimal setting.

## A reviewer should record

- Platform, app version/commit, Reference backend version and selected settings.
- Whether controls respond, the busy indicator is visible and the current job is
  unambiguous. Record any failure, rather than silently correcting it off-record.
- Whether a safe cancellation and reopening preserve completed work and decisions.
- The run ID, actual visual judgements, report/CSV/PDF agreement and any limitation.

Use [the observed engineering evidence](PUBLIC_REFERENCE_OBSERVATION.md) as a
bounded example, not a target that the reviewer must reproduce by changing their
answers. Native independent first-use acceptance remains a separate, open gate.
