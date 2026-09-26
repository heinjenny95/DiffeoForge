# v91: pilot decisions, windows and PC shape generation

The PC shape generation route now passes the shared Windows no-console policy
to its injected process runner. Previously this call escaped the guard used by
direct subprocess launches, allowing a WSL console to appear. Regression coverage
now includes injected launcher defaults and aliases, the actual endpoint call,
and Windows child-console allocation.

The pilot is an independent modeless window with minimize/restore controls and
one retained controller. Progress never activates or restores it. The main
project controls remain disabled while it is open; closing the main window or
pressing Escape cannot abandon a running pilot. Closing an idle pilot applies
completed successor parameters once and restores the main controls.

## Anatomical decisions before numerical economy

Deformation magnitude and atlas/reconstruction area changes are neutral contextual
measurements. A low cost with missing important anatomy can indicate underfit;
large true differences can require substantial deformation. Neither magnitude
alone proves registration quality. This does not remove backend regularization.

Assessment v0.5 ranks explicitly visually accepted, numerically eligible options
first, when any exist. Unreviewed options remain available for deliberate manual
review/selection; rejected options and automatic hard failures remain excluded.
Cost/runtime priorities apply within the accepted set. With no accepted options,
the previous disparity-aware numerical policy remains a provisional shortlist.
One accepted option does not become an automatically robust numerical optimum.

The interface exposes actual score weights, per-specimen nearest-vertex p95
values, the limits of pooled geometry proxies, and optional anatomical notes.
Visual decisions and notes are saved immediately as hash-bound ledger events,
survive reopening and take precedence over stale AFK decisions. They require
inspection of all original-detail specimen pairs. Existing completed studies,
stored assessments and researcher choices are not rewritten or re-approved.

Optional feature checks are dataset-specific: the researcher names the relevant
feature/region and records preserved, not preserved or uncertain per specimen.
Paired counts are optional when a quantitative count is meaningful. No particular
anatomy or feature is preselected for future datasets. Unresolved/failed feature
checks or unequal/incomplete entered counts block a pass in both interface and
persistence API. Criteria, observations and counts survive navigation/reopening.
These are researcher observations, not automatic mesh detections; agreement on
one criterion alone does not establish overall anatomy or homology.

Per-specimen distances still cannot establish homology or protect every small
tip, tooth or branch. Automatic local anatomical scoring remains unvalidated.
Independent prospective anatomical review is still required; no dataset-specific
weights or preferred-candidate rule were introduced.

## Verification and boundaries

174 targeted regressions passed before the final dataset-generic feature wording
and schema change; all 49 affected study/dialog/lifecycle regressions passed again
after that change. Focused Ruff and whitespace checks pass. The synthetic feature
review layout was inspected with readable Windows fonts.

Targeted checks cover the assessment across low/moderate/high/extreme disparity,
saved rejection/acceptance, changed-evidence detection, review completeness,
stage transitions, modeless lifecycle, minimize/progress/restore, PC endpoint
generation and existing QC behavior. Native Windows minimize/restore and absence
of a native owner were observed with idle and simulated running controllers.
The execution desktop did not expose another foreground window, so inter-application
focus retention is an outstanding interactive acceptance check. No scientific
engine run was used for this window check.

A broader legacy desktop test attempt exposed stale required-label expectations,
an incomplete QC-context fixture and a parameter-worker dispatch expectation;
a landmark-editor test stalled in a modal warning. These unrelated cases are
not evidence that the full desktop suite passes. Scoped pilot/PC/QC tests and
frozen-build checks are reported separately in the delivery record.

Installer creation/distribution and installation are separate. Building v91
does not authorize replacing the installed application or running a new atlas.
