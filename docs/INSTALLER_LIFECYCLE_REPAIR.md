# Installer lifecycle evidence: version-aware registration

The Windows lifecycle jobs at the preprint baseline and v82 failed after setup
completed, at the observer's current-user uninstall-registration check. The
observer still required the literal `DiffeoForge 0.0.0.dev0` display name. The
installer now correctly uses numbered private-alpha display labels.

The observer now compares both DisplayName and DisplayVersion against the exact
compiler defines from the verified, hash-bound installer build plan. Legacy
plans without AppDisplayVersion retain Inno's AppVersion fallback. Missing,
duplicate, empty or inconsistent version defines fail closed. The setup, source,
installed-file inventory, shortcut, uninstall and project-sentinel checks remain.

Regression tests cover dev0, v82, a future numbered alpha and release-style
versions, plus invalid defines. The fresh [ephemeral Windows lifecycle run on
cd8c1be](https://github.com/heinjenny95/DiffeoForge/actions/runs/35081181366)
passed isolated installation, smoke start, uninstall and project preservation.
General CI and the public Reference-container comparison also passed on that
commit. Repeat candidate-specific evidence after relevant changes. No installer
was run against the researcher's installed application.

Failure evidence: [v82 lifecycle run](https://github.com/heinjenny95/DiffeoForge/actions/runs/35069224019).
This diagnosis does not establish signing, public release readiness, native
interactive usability or scientific validity.
