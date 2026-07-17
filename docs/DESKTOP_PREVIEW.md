# Desktop setup, review, and Modern compute preview

Status: **four graphical steps with verified Modern CPU execution and result review;
no installer**

Tracked by [engineering issue #75](https://github.com/heinjenny95/DiffeoForge/issues/75)
and [engineering issue #77](https://github.com/heinjenny95/DiffeoForge/issues/77),
with the compute screen tracked by
[engineering issue #83](https://github.com/heinjenny95/DiffeoForge/issues/83)
and result review tracked by
[engineering issue #85](https://github.com/heinjenny95/DiffeoForge/issues/85).
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
4. optionally select a labelled-landmark CSV for the modern workflow;
5. validate schemas, paths, mesh geometry, and the engine-specific setup
   contract through the same application services used by the CLI;
6. create a non-overwriting starter configuration and review a visible result
   summary;
7. continue to a second screen that reads the effective values back from the
   validated configuration and explains their role;
8. for the modern route, generate and render the existing exact-count
   `modern-plan` JSON/HTML evidence; or, for the reference route, render the
   existing preflight parameter ratios and external-engine boundary;
9. for a reviewed Modern project, continue to a third screen that binds the
   exact reviewed configuration SHA-256, displays and refreshes the read-only
   destination/private-state evidence, checks it again immediately before
   starting the separate worker, shows real workflow stages and committed
   optimizer decisions, and offers one cooperative cancel action; and
10. expose the result directory only after the parent controller independently
    verifies the published workflow, manifest hash, subject count, and bundle;
11. continue to a fourth screen only after a fresh full verification of the
    workflow, nested bundle, exact inventories, hashes, mesh QC, and static SVG
    safety checks; and
12. inspect bounded Atlas, optimizer, momenta-PCA, and QC summaries, then open
    only inventoried VTK/CSV/JSON/SVG artifacts whose manifest bindings, size,
    and SHA-256 pass again immediately before handoff to a local application.

The reference path creates `atlas.yaml` and `atlas.preflight.html`. The modern
path creates `modern-atlas.yaml` after its stronger mesh-quality,
initialization, optional Procrustes, and PCA-dimension checks pass. Its second
screen publishes `modern-atlas.workload/workload.json` and `workload.html`.
Both paths label geometry-scaled values as exploratory. Only the Modern route
can currently continue to numerical work; the external reference button stays
explicitly unavailable rather than implying unsupported supervision.

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

- Existing configurations and reports are never silently overwritten.
- Review refreshes only reports that carry the expected DiffeoForge generator
  markers; researcher-owned paths are refused.
- Mesh inspection runs in a background GUI thread. Modern numerical work runs
  in a separate child process supervised by the fail-closed parent controller;
  Qt receives only validated events through queued signals.
- The launch must match the SHA-256 captured by the completed review. An edited
  configuration is refused until it is reviewed again.
- Before launch, the compute page shows the exact destination, whether it
  exists, and every exact-name private candidate's raw status, path, and reason.
  Refresh and the mandatory immediate pre-launch recheck are read-only; the GUI
  exposes no delete, rename, resume, or publish action for private state.
- The compute page shows exact completed stages and optimizer decisions. It
  does not turn them into an ETA, runtime estimate, peak-memory claim, or
  invented percentage.
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

## Current limitations

The GUI does not yet edit scientific parameters, render meshes natively, resume
a Modern atlas, reconcile an already dead parent application, or supervise the
external Deformetrica engine. Step 4 is a detailed read-only evidence and
artifact-handoff view, not an interactive 3D renderer or a scientific
interpretation system. The application is not frozen with PyInstaller and is
not wrapped in an Inno Setup installer. Those capabilities require their own
tests and release gates.

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
