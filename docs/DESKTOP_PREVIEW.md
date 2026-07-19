# Desktop setup, review, and Modern compute preview

Status: **four graphical steps with verified Modern CPU execution and result review;
same-owner private-alpha installer available**

Tracked by [engineering issue #75](https://github.com/heinjenny95/DiffeoForge/issues/75)
and [engineering issue #77](https://github.com/heinjenny95/DiffeoForge/issues/77),
with the compute screen tracked by
[engineering issue #83](https://github.com/heinjenny95/DiffeoForge/issues/83)
and result review tracked by
[engineering issue #85](https://github.com/heinjenny95/DiffeoForge/issues/85).
The read-only reference-environment card is tracked by
[engineering issue #95](https://github.com/heinjenny95/DiffeoForge/issues/95).
The approval-bound read-only preparation-status card is tracked by
[engineering issue #133](https://github.com/heinjenny95/DiffeoForge/issues/133).
The native template projection preview is tracked by
[engineering issue #97](https://github.com/heinjenny95/DiffeoForge/issues/97).
The English alpha-smoke follow-up, confirmed atomic overwrite, explicit
convergence status, and 10,000-face planning contract are tracked by
[engineering issue #177](https://github.com/heinjenny95/DiffeoForge/issues/177).
The distribution architecture and its stricter release gates remain in
[Desktop executable and installer architecture](DESKTOP_DISTRIBUTION.md).

## What works now

The optional PySide6 application provides one complete setup path without a
terminal:

1. choose the modern CPU or external Deformetrica 4.3 reference engine;
2. select a directory of VTK meshes and an explicit template, or allow only a
   literally named `template.vtk` to be detected;
3. select the coordinate unit, project directory, optional project name, and
   subject filename pattern;
4. for the Modern route, explicitly choose the dense small-pilot baseline or
   the exact `256 × 256` blockwise high-face-count experiment;
5. explicitly choose either a three-cycle technical pilot or a convergence
   attempt capped at 50 cycles, with early stopping only when every parameter
   block reaches the declared gradient tolerance in one completed cycle;
6. optionally select a labelled-landmark CSV for the modern workflow;
7. validate schemas, paths, mesh geometry, and the engine-specific setup
   contract through the same application services used by the CLI;
8. create a starter configuration, requiring a destructive confirmation before
   atomically replacing only a recognized DiffeoForge-generated configuration,
   and review a visible result summary;
9. continue to a second screen that reads the effective values back from the
   validated configuration and explains their role;
10. optionally load the exact selected template outside the event loop and view
   native aspect-preserving XY, XZ, or YZ wireframe projections with source
   hash and displayed/total edge counts;
11. for the modern route, generate and render the existing exact-count
   `modern-plan` JSON/HTML evidence; or, for the reference route, render the
   existing preflight parameter ratios and external-engine boundary, then
   optionally diagnose the exact configured container engine and image without
   changing or starting either one, then inspect one externally hash-bound
   preparation approval and its exact destination/private-stage state through
   the shared read-only reconciliation core;
12. for a reviewed Modern project, continue to a third screen that binds the
   exact reviewed configuration SHA-256, displays and refreshes the read-only
   destination/private-state evidence, checks it again immediately before
   starting the separate worker, shows real workflow stages and committed
   optimizer decisions, and offers one cooperative cancel action; and
13. expose the result directory only after the parent controller independently
    verifies the published workflow, manifest hash, subject count, and bundle;
14. automatically continue to a fourth screen only after a fresh full
    verification of the workflow, nested bundle, exact inventories, hashes,
    mesh QC, and static SVG safety checks; and
15. inspect bounded Atlas, optimizer, momenta-PCA, and QC summaries together
    with an embedded verified objective/gradient convergence plot plus verified
    PC1/PC2 and PC2/PC3 score plots, then open only
    inventoried VTK/CSV/JSON/SVG artifacts whose manifest bindings, size, and
    SHA-256 pass again immediately before handoff to a local application.

The left workflow rail is state-aware navigation rather than a passive progress
legend. A completed or otherwise available step can be opened directly; future
steps and all navigation during an active worker remain disabled. The fixed
bottom-right primary action also advances with the workflow: project creation
becomes parameter review, atlas launch becomes verified Results & PCA review,
and a completed review can be reopened without exposing duplicate primary
actions inside result cards.

The reference path creates `atlas.yaml` and `atlas.preflight.html`. The modern
path creates `modern-atlas.yaml` after its stronger mesh-quality,
initialization, optional Procrustes, and PCA-dimension checks pass. Its second
screen publishes `modern-atlas.workload/workload.json` and `workload.html`.
Both paths label geometry-scaled values as exploratory. Only the Modern route
can currently continue to numerical work; the external reference button stays
explicitly unavailable rather than implying unsupported supervision. A passed
reference diagnostic proves only its listed host/container observations; it is
not a hidden launch prerequisite or evidence of a completed atlas.

## Developer launch

This is a source preview, not an installation instruction for researchers:

```powershell
python -m pip install -e ".[desktop,modern-engine]"
diffeoforge-desktop
```

The base `diffeoforge` package and command-line workflow do not import Qt.
Without the optional desktop dependency, the launcher exits with a focused
installation message. The packaging seam can be checked without entering the
event loop:

```powershell
python -m diffeoforge.desktop --smoke
```

## Safety and privacy boundary

- Existing configurations are never silently overwritten. The setup screen asks
  for destructive confirmation and then atomically replaces only a file with
  the expected DiffeoForge generator marker; cancellation and write failure
  preserve the prior bytes. Generated review reports retain their own strict
  ownership checks.
- Review refreshes only reports that carry the expected DiffeoForge generator
  markers; researcher-owned paths are refused.
- Template preview loading runs outside the GUI event loop, checks the source
  SHA-256 before and after parsing, and never rewrites or decimates the mesh.
  Projection switches reuse the same immutable model. A deterministic 20,000-
  edge display budget is always shown when it omits edges.
- The reference-environment check parses the exact reviewed configuration
  bytes, uses their configured container engine/image, and checks the file hash
  again afterward. It shows raw doctor evidence but performs no install, image
  build/pull, run preparation, backend start, resume, recovery, or repair. A
  passing result unlocks the separate supervised execution page.
- The reference preparation-status check requires the previously reviewed
  approval file plus its independently recorded complete-file SHA-256. It runs
  outside the event loop, remains bound to the completed config review, and
  discards results after any approval/config input drift. It exposes no prepare,
  publish, delete, rename, repair, resume, recovery, or execute action.
- Mesh inspection runs in a background GUI thread. Modern numerical work and
  Deformetrica execution use distinct child processes supervised by fail-closed
  parent controllers; Qt receives only validated events through queued signals.
- The launch must match the SHA-256 captured by the completed review. An edited
  configuration is refused until it is reviewed again.
- Before launch, the compute page shows the exact destination, whether it
  exists, and every exact-name private candidate's raw status, path, and reason.
  Refresh and the mandatory immediate pre-launch recheck are read-only; the GUI
  exposes no delete, rename, resume, or publish action for private state.
- The Modern compute page shows exact completed stages and optimizer decisions
  without an ETA, runtime estimate, peak-memory claim, or invented percentage.
  The Deformetrica page shows observed iterations and objective components. Its
  rolling estimate is labelled ETA to the configured iteration cap and explicitly
  not convergence.
- Normal window close while compute is active requests cooperative cancellation
  and keeps the window alive until the worker has a reconciled terminal state.
- Result review and per-artifact verification also run outside the GUI event
  loop. A close request waits for those read-only checks to finish; it never
  opens an artifact after a close was requested.
- Project files stay in the user-selected directory, separate from future
  application files.
- The window performs no upload, telemetry, update check, or network request.
- A passed setup proves supported file/schema/geometry checks only. It does not
  establish biological validity, parameter suitability, Deformetrica
  equivalence, or production suitability for more than 300 specimens.
- The blockwise high-face-count choice preserves exact all-pairs mathematics and
  bounds one declared pairwise tile allocation. It does not promise total RAM,
  runtime, convergence, or 300-subject feasibility. See
  [High-detail surface workflow foundation](HIGH_DETAIL_SURFACES.md).

## Current limitations

The GUI does not yet edit scientific parameters, render meshes interactively in
3D, place landmarks, resume an atlas, or reconcile an already dead parent
application. Verified Deformetrica momenta now enter the shared PCA screen;
reference PC deformation meshes and registration renderings remain open.
Source-level Deformetrica supervision is connected, but its dedicated execution
worker is not yet part of the frozen Windows bundle. The projection preview is
not mesh QC or registration evidence. Step 4 is a detailed read-only evidence and
artifact-handoff view, not an interactive 3D renderer or a scientific
interpretation system. A developer-machine PyInstaller one-directory evidence
freeze exists, but it is not a redistributable release and is not wrapped in an
Inno Setup installer. Those capabilities require their own tests and release
gates.

## Preliminary Qt licensing boundary

The desktop extra currently installs the smaller official
`PySide6-Essentials` distribution because this slice uses only QtCore, QtGui,
and QtWidgets. It remains an optional PySide6 dependency and does not change
DiffeoForge's MIT license. Qt for Python is offered under LGPLv3/GPLv3 and
commercial terms, and contains components with additional third-party notices.
The official Qt guidance also describes distribution duties for LGPL builds,
including prominent notice, license/source availability, relinking rights, and
a complete review of the libraries actually shipped:

- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/)
- [Licenses used in Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qt for Python package details](https://doc.qt.io/qtforpython-6/package_details.html)
- [Qt's LGPL obligations overview](https://www.qt.io/development/open-source-lgpl-obligations)

This repository does not claim that a future frozen binary is compliant merely
because this source preview launches. Before any installer is distributed, the
exact frozen Qt modules and all transitive licenses must be inventoried, notices
and corresponding-source instructions must be included, relinking constraints
must be reviewed, and the result must receive an appropriate legal review.
