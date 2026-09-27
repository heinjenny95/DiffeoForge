# v93 — explicit project paths and input validation

The setup screen starts with empty path fields and no remembered coordinate unit.
**Load last project paths** explicitly fills the mesh, project, template and
landmark paths, file pattern, project name, engine and recorded unit. The existing
recent-project chooser remains available. Neither action opens a run or performs
mesh validation.

**Run deep mesh validation** is the only setup-preflight dispatch action. Pasting,
Enter, focus changes, browsing, landmark import/placement and alignment-setting
changes do not start it. One worker may run at a time. If inputs change during a
check, its result is discarded and the interface asks for another explicit click;
it never queues another full cohort inspection. Unchanged successful checks are
reused. After an error, retry is explicit and error-dialog focus cannot start it.

Landmark CSV names and structure are checked before any mesh topology work.
Missing or unsupported landmark paths are surfaced rather than silently ignored.
Progression into parameter setting requires a current, completed check with no
blocking findings. Advisory findings still permit progress; topology and landmark
quality gates are unchanged. Existing completed-run and checkpoint entry points
retain their independent verification.

This changes desktop workflow only: no scientific mesh decimation, parameter
change, alignment approval or automatic pilot/atlas launch is introduced.
The familiar theme and pilot-window behavior remain intact.

Verification: 178 scoped regressions passed, covering input checks, project
history/setup, landmark import/editor, preprocessing, activity and existing-project
navigation. After the final compact two-row history layout, all 46 affected
preflight/history/version/resume tests passed again. Ruff and diff whitespace
checks passed. Synthetic offscreen views at 1280 and 1100 pixels were inspected
with the existing Windows fonts/theme, including blank startup, restored inputs
and the validation button below the input fields. A stale legacy resume-test
fixture was updated with the existing QC-source field; production QC logic did
not change. This is not a new full-suite or scientific-acceptance claim.

The versioned build and delivery are recorded separately after verification.
Source, installed application and Drive distribution remain distinct; the
previously installed/distributed v92 is not claimed to contain this fix.
