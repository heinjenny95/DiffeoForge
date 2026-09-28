# v96 verified build and distribution

Snapshot: 2026-09-28. This is software delivery evidence, not scientific fit
approval or a public release. See [implementation and limits](V96_ADAPTIVE_PILOT.md).

## Identities

- Tested runtime: `0.0.0.dev96`, source
  `5a069968d5f8adee639ad60f347a9f6e4767b2fe`.
- Installer: `DiffeoForge-v96-Windows-CPU-x86_64-Setup.exe`, 323,464,693 bytes.
- Installer SHA-256:
  `ead1311339a8e07d6620aed8c2e6a620ad020fd5269bdd60bdeabccc74645cf4`.
- Latest Drive-distributed runtime: v96, complete verified package.
- Local installed runtime: **v95 remains installed**. The main application is
  still open; v96 installation awaits safe closure. Standing installation
  authorization remains in force. No application or scientific job was stopped
  to install this build. A fresh idle check and verified backup are required
  before the prepared installation procedure is used.

Later documentation commits do not change the built runtime source identity.

## Verification

168 distinct scoped regressions passed across batches, with Ruff, synthetic UI
inspection and a synthetic Deformetrica 4.3.0 cold/warm compatibility test.
Frozen GUI and workers passed startup, cancellation, parent-death and reference
preparation checks. Bundle, dependency, SBOM and installer checks passed.
The installer was built but has not been executed on the owner's installation.

All four binary parts, the reconstruction script and companion README were
uploaded, downloaded through authenticated and anonymous routes, and compared
by size and SHA-256. Both downloaded scripts reconstructed the exact verified
installer without executing it. Only then was the stable current-download README
replaced in place; authenticated and anonymous readback matched its local bytes.
Existing sharing and stable links remain unchanged; the complete v95 package
remains recoverable. Private receipt paths and destination identities remain in
the owner's artifact workspace.

## Remaining acceptance

Install and verify v96 after safe application closure. Prospective specimen fits,
independent first-use acceptance and native interaction remain open. No private
scientific fit or full atlas was started for this implementation; test success
does not demonstrate anatomical fidelity. The bounded search is not a global
optimizer and cannot guarantee a satisfactory fit for every dataset.
