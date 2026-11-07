# v93 build, installation and distribution

Verified 2026-09-27. Version **0.0.0.dev93**, runtime source
[`bf65eb9f85b42d36dcc97df46ed0909f20a95b4c`](https://github.com/heinjenny95/DiffeoForge/commit/bf65eb9f85b42d36dcc97df46ed0909f20a95b4c).
Later documentation commits do not change the frozen runtime identity.

The [input-validation change](V93_INPUT_VALIDATION.md) passed 178 scoped
regressions and 46 final affected tests, Ruff and synthetic visual inspection.
Frozen startup, worker execution/lifecycle harnesses, preparation-only checks,
bundle inventory, dependency metadata, SBOM and installer verification passed.
No private scientific pilot or atlas was started by this update.

| Artifact | Verified identity |
| --- | --- |
| Installer | `DiffeoForge-v93-Windows-CPU-x86_64-Setup.exe` |
| Installer bytes | 323,252,213 |
| Installer SHA-256 | `c087218762216ecc390b216ae64cc5f1ff08e0a6d9acd59d6b0fdd77748f8328` |
| Build-evidence SHA-256 | `0efd82dbabc7e9ae9073ca73b38f3a3980df0b9b1c71f646bc732bbe62260827` |
| Installed executable SHA-256 | `0dd4f7c10e032d2fce731c21d2dcb2dcca7497db85eee45e1d97d05cb3bcde74` |

The owner saved work and closed the application. Fresh application/WSL idle
checks preceded a complete 2,688-file, hash-verified v92 backup and installation.
Setup exited successfully. Registry version, all 2,679 installed bundle files
and installed startup smoke passed. The 351 checked completed-run files remained
unchanged; no user process was stopped to perform the update.

The established Drive channel now offers the complete v93 package: four binary
parts, a hash-checking reconstruction script and README. All six files were
downloaded through authenticated and anonymous routes and matched their local
sizes and hashes. Both reconstructed installers matched the verified installer.
Only then was the existing current-README file updated in place; both download
routes verified its 3,791 bytes and SHA-256
`7aaf89e6228b53a740e68dc96636732ee4be6cbc8c9a811613dea6d181c9b94e`.
Existing IDs/sharing were preserved where applicable, and v92 remains recoverable.

This is a tested private-alpha delivery, not a signed/public release, new full
test-suite qualification, native multiplatform acceptance or scientific approval.
No GitHub Release, tag, merge or research-data upload was performed.
