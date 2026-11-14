# Source UI and R handoff follow-up — 27 October 2026

This change is source-only. The owner is testing the previously installed pilot
and explicitly deferred any new installation until a later go-ahead. No version
bump, installer build, installation or installer upload is part of this change.

## Behavior

- The landmark editor shows placement guidance, retains the source-bound picking
  workflow, and offers a bounded, scrollable detailed guide. Compact outlined
  actions and a smaller minimum canvas let it fit a 900 × 720 window.
- Initial-template guidance explains anatomical completeness and representativeness.
  The existing background analysis is labelled clearly; it still requires an
  explicit selection and does not launch a fit.
- Alignment help follows each existing size policy and the reflection choice.
  Method descriptions explain tangent PCA, PCoA, Cartesian PCA and nonlinear
  alternatives without changing numerical IDs, settings or presets.
- Visualization separates five display tabs, labels current-view exports, offers
  R export and preserves readable light/dark tab states. Axis padding keeps
  ordinary mesh glyphs clear of tick labels without jittering scores. Very large
  glyphs or dense specimens can still overlap; glyph size remains adjustable.
- Base R receives the saved reviewed PCA. geomorph receives supplied homologous
  fixed landmarks for a separate analysis. Both exports verify sources and ZIP
  bytes and preserve existing destinations. See [the export contract](R_EXPORT.md).
- The repository homepage is a shorter user entry point with a synthetic source
  screenshot and guide links. Its previous detailed catalogue is retained in the
  [engineering reference](ENGINEERING_REFERENCE.md); local links are checked.

## Verification and limits

64 focused checks pass: 60 export/guidance/viewer/landmark/pilot regression cases,
three existing main-window integration cases and one additional test of all
three main-window R-export entry points. R 4.5.2 and the already installed
geomorph package execute the generated scripts on synthetic data. Checks cover
array axes and specimen order, leading zeros, literal NA, UTF-8 names, finite
non-collinear landmarks, changed sources, exclusive publication and GUI
responsiveness. Full repository lint and whitespace checks pass.

Sixteen styled source-layout cases pass on the native Windows Qt platform and
another sixteen offscreen, spanning light/dark modes, three landmark/viewer
sizes, two method-dialog sizes and all five visualization tabs. Private review
sessions use separate INI settings and test state; process dispatch is blocked.
These are source-widget checks, not a frozen-package or installer qualification.

A stale alignment-test fixture also fails on the unchanged starting commit:
it requests automatic method comparison in explicit Advanced setup, so it never
reaches its intended stale-alignment gate. The fixture now selects an explicit
method and verifies that changed landmarks still prevent project creation.
Existing test-only lint formatting is corrected without changing behavior.

The installed pilot, owner projects, existing fits, scientific objectives and
acceptance thresholds are untouched. Current owner pilot feedback and approval
of the new interface remain open. No new owner atlas, fit or anatomy approval
is inferred from these engineering checks.
