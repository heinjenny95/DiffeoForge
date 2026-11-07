# v123 — presentation delivery

The verified Windows CPU private-alpha build is installed locally. Runtime freeze
source: `423f045de5796a03cf595dd35b1ceaa5b59359de`; presentation implementation:
`cecd3b2`. Later delivery-document commits do not change these installed bytes.

Verification completed:

- Broader desktop, launcher, optional-engine, freeze and installer regression
  suite: 89 passed, one expected optional-dependency negative-case skip. Final
  focused demo suite: 13 passed, overlapping the broader suite.
- Ruff and diff checks; embedded public source hashes match committed source
  bytes; wheel includes all five resource files with identical fixture bytes.
- All eight stations visually inspected, including a compact viewport. Actual
  picking, recorded replay, camera controls, reset and normal-gate isolation pass.
- Frozen application and worker/startup/cancel/parent-death boundary checks pass.
  Frozen and installed demo bytecode executes with the packaged resources, and
  both normal and `--demo` installed smoke entry points return zero.
- All 2,837 runtime/freeze files and six evidence companions match the verified
  bundle. A complete previous-version backup and fresh idle checks preceded
  installation; tracked completed-result evidence remains byte-identical.
- Demo desktop and Start Menu shortcuts were read back with the exact `--demo`
  target. The per-user installer preserved an earlier no-Start-Menu preference;
  the local presentation shortcut was added separately without changing setup
  policy or replacing unrelated shortcuts.
- The separately deployed remote computation was observed healthy and was not
  modified. No private fit, anatomy approval, PCA, credential change or server
  operation was performed for this delivery.

See [presentation scope and limitations](V123_PRESENTATION_MODE.md). Recordings,
illustrative controls/blends and report previews remain explicitly identified.
The demo is not a scientific project, result bundle or approval shortcut.

This is a private-alpha engineering delivery, not a signed release or a universal
scientific qualification. No Drive upload, public release, tag or merge occurred;
the previously distributed package remains unchanged.
