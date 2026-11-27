# v90 distribution reconciliation

Verified on 2026-09-25. The established owner-managed Drive channel now offers
the same **v90 / 0.0.0.dev90** installer as the tested local installation,
closing the previously recorded v71 distribution lag.

## Artifact identity

- Runtime source: `a17e89acca38174bf7a512d1aeab33d921aac693`.
- Installer: `DiffeoForge-v90-Windows-CPU-x86_64-Setup.exe`.
- Size: **323,206,604 bytes**.
- SHA-256: `1a34e7399fb50a0c81c311ccec3f6f5ed55d3fa43e035f5b75640d6d2beabaac`.
- Installed executable SHA-256:
  `39544c3cab104ed705357d35fdebe5304ccc9c5e91998b71c58c4fbb3c967752`.

The installer and installed executable were rehashed against existing delivery
evidence; the installed registry version remains `0.0.0.dev90`. No application
rebuild, installation, dependency update or scientific calculation was performed.
This documentation commit is separate from the runtime source identity.

## Complete package and verification

The connector rejected a single-file upload before invocation because its
per-file limit is 100 MiB. The unchanged installer is therefore distributed as
four consecutive binary parts: three at 80 MiB and one at 71,548,364 bytes.
These are parts of the executable, not ZIP archives. A companion PowerShell
script verifies every part, reconstructs the executable, checks its complete
SHA-256 and refuses to overwrite a different existing output. It never launches
the installer.

All four parts were downloaded through the authenticated connector and again
without authentication. Both downloads matched their expected lengths and
SHA-256 hashes. Running the downloaded reconstruction script against the
downloaded parts produced the exact installer identity above. The companion
README was downloaded and compared byte-for-byte.

The complete versioned set was staged and checked before changing the current
README. Its existing Drive file ID/link was retained. The nine original v71 ZIP
parts remain in place with unchanged file IDs, sizes and modification timestamps;
their original README was copied and its content verified before the current
README was replaced. Existing folder sharing was preserved. Detailed destination
IDs and download receipts remain in the private delivery workspace.

## Scope and remaining acceptance

The README records version, provenance, checksums, reconstruction and installation
instructions, the unsigned installer, and the Drive download-confirmation notices
observed for the first binary part and the reconstruction script. Downloads and
reconstruction are verified; hash equality is not malware clearance or anatomical
approval.

Existing v90 evidence remains 185 targeted regressions, Ruff, synthetic GUI
inspection, frozen GUI/worker and installed-startup checks, and 2,679 installed
bundle-file comparisons. These were not repeated or relabelled as a new full
suite. Native user acceptance and independent scientific/mathematical review
remain open. No private study data or installer bytes enter this repository,
and no GitHub Release, tag or manuscript submission was created.
