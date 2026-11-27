# v91 build and distribution

Verified on 2026-09-26. The established owner-managed Drive channel now offers
**v91 / 0.0.0.dev91**. The same build was subsequently installed after owner
authorization, a verified v90 backup and a fresh idle check. No new scientific
calculation was started.

## Artifact identity

- Runtime source: `5730920625a015e34f63d843c7435f311b89c993`.
- Installer: `DiffeoForge-v91-Windows-CPU-x86_64-Setup.exe`.
- Size: **323,245,725 bytes**.
- SHA-256: `c81edd668b539c9884f69c8a44fbc763aa317d9ad59ec80c5fc75fe121c25f7c`.
- Installer build-evidence SHA-256:
  `b537d3866ef717f30236b60532a2125a07d4bb8509bea587ac95af1c1b485032`.

The clean source was frozen and packaged with consistent version and source
identity. Frozen GUI/worker smoke checks, cancellation/parent-death checks,
2,677-file bundle inventory, dependency/SBOM checks and installer verification
passed. The installer is unsigned. The later delivery-documentation commit is
separate from the runtime source above; it does not require an identical rebuild.

## Complete package verification

The installer is split into four consecutive binary parts: three at 80 MiB and
one at 71,587,485 bytes. The six-file set also contains a README and a PowerShell
join script that validates the parts and complete executable without launching
the installer. It refuses to overwrite a different existing executable.

All six files were downloaded through the authenticated connector and again
without authentication, with exact byte lengths and SHA-256 matches. Both sets
were reconstructed using the downloaded join script; both complete installers
match the identity above. Download-confirmation notices were observed for the
first binary part and the script and are described in the README.

Only after these checks was the existing current-README file updated in place.
Its ID/link, parent and sharing were retained; authenticated and anonymous
readback matched the versioned README byte-for-byte. The complete prior v90
package and its versioned instructions remain recoverable. No sharing permissions
were changed. Detailed destination IDs and receipts remain private.

## Acceptance limits and next step

Source verification comprises 174 targeted regressions and, after generalizing
feature checks, another pass of all 49 affected study/dialog/lifecycle tests.
Focused Ruff and synthetic layout checks passed. See
[implementation and test limitations](V91_PILOT_REVIEW.md), including unrelated
legacy desktop-test failures rather than a fresh full-suite claim.

Native Windows minimize/restore and controller retention were observed with idle
and simulated running controllers. The test desktop provided no foreground
window handle, so actual cross-application focus acceptance remains open.
Feature observations are human supplied and dataset-specific; numerical scores
do not validate anatomy or homology. Existing studies and completed atlas results
were preserved.
No GitHub Release, tag, public installer asset or research-data upload was made.

## Installed verification and standing authorization

The application and WSL distributions were inactive before installation. All
2,688 files in the previous installation were copied to a recoverable backup and
hash-compared. Setup completed with exit code zero and no restart requirement.
The registry reports `0.0.0.dev91`; all 2,679 files in the completed bundle,
including its two added evidence files, match the installation. The installed
executable SHA-256 is
`c6ded61ea5e42bdf11efe22e956accfd6b2454b0e11835a81629ddfa3633ea75`.
The installed startup smoke passed. All 351 checked completed-run files retained
their hashes. These checks do not close the interactive focus acceptance above.

The owner also established that approval to develop a new version includes
installing its tested build without another confirmation. This rule is persisted
in `AGENTS.md`; backup, idle checks and preservation of ongoing/unsaved work still
apply. The companion Drive instructions were updated in place; installer parts
and runtime source identity remain unchanged.
