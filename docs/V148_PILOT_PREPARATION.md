# v148 — prepare the currently selected pilot project

With an earlier project loaded, changing the project directory or matching method
could leave the pilot action enabled while its handler immediately rejected the
stale project binding. The footer action could also navigate using the previous
review. Repeated clicks did not prepare the new configuration. This was an
application workflow defect, not a mesh-fitting or backend failure.

Both explicit preparation actions now prepare the current form through the
existing project creation, review and environment-check chain. They retain the
current guided-plan requirement and the ordinary configuration-overwrite prompt.
Cancelling that prompt preserves the loaded project and configuration. An active
worker prevents a second preparation; no stale readiness or completed selection
can stand in for the newly selected project. Unchanged projects retain the
existing continuation path.

Six new regression cases fail against v147 before the repair. Seven preparation
cases and eleven engine-switch cases pass after it, including both visible
actions, project/method edits, repeated clicks, cancelled overwrite and a stale
plan. A source probe exercises both buttons through the actual asynchronous
project/review/readiness workers and the actual pilot opener on public synthetic
geometry. Only the external environment diagnostic result is simulated; native
dispatch is guarded while both pilot windows open with zero attempted fits. The
existing six-trial comparison orchestration is
also checked with simulated controllers. No native fit, atlas or PCA is started.

The 57 existing comparison/setup/version cases and three additional desktop
cases pass. The expanded saved-pilot responsiveness module has seven passing
cases and two pre-existing callback-count assertions: both failures reproduce
unchanged when all four modified window methods are restored from v147. Tampered
evidence is still rejected before the downstream loader. These baseline
assertions are recorded separately and are not repaired or claimed as passing.

The installed v147 cannot acquire this change while running. Installation of
the tested successor requires a verified backup and an idle application/backend;
unsaved owner work and an active recording must be preserved. Runtime/delivery
verification is recorded separately after the candidate build is tested.
