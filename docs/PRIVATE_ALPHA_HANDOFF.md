# Same-owner local Windows private-alpha handoff

Status: **first exact same-owner local handoff accepted**

The private-alpha handoff is the first deliberately installable DiffeoForge
artifact intended for the repository owner's own Windows account. It is a
testing boundary between engineering installer evidence and a public release.

`tools/package_private_alpha.ps1` accepts only an externally hash-bound,
independently reconstructed `installer-build-evidence.json` from the exact
clean source commit. The retained engineering setup must remain unsigned,
unexecuted, non-distributable, and non-release-authorized. Packaging does not
change those claims; it permits one same-owner local copy for testing.

Create mode publishes atomically to a new directory under the current Windows
user profile and outside the source repository. It refuses overwrite and
creates exactly six files:

- `DiffeoForge-0.0.0.dev0-Windows-CPU-x86_64-Setup.exe`;
- `PRIVATE-ALPHA-README.txt`;
- `LICENSE.txt`;
- `windows-security-observation.json`;
- `private-alpha-manifest.json`; and
- `private-alpha-manifest.sha256`.

The security observation independently checks Authenticode. When Microsoft
Defender is enabled and exposes `Start-MpScan`, the wrapper requires a targeted
scan without a matching threat observation. Disabled or unavailable Defender
is recorded explicitly. Windows Security Center product presence is inventory,
not proof of a scan or malware clearance.

Verify mode takes the directory and an externally recorded manifest SHA-256.
It rejects every extra, missing, symbolic, renamed, or content-changed file and
rechecks the setup/build and security bindings without executing the setup.

This handoff is not signed, publicly uploaded, redistribution-approved,
scientifically validated, numerically qualified for an exact setup, or tested
at 300-specimen scale. The tester must preserve independent source-data backups.

## First accepted handoff

The first handoff was created on July 18, 2026, from clean source commit
`0b4eb25724a9914aefb1afa8134764cc0199eb61`. It was published only to the
repository owner's local Desktop folder named
`DiffeoForge Private Alpha 0.0.0.dev0 (0b4eb25)`; it was not uploaded.

- Installer-build evidence SHA-256:
  `1686171bcb52d9eb6b8916b9c511f471c5be8c7d575105c9b59f3d44c989f4ac`.
- Setup: 259,317,401 bytes; SHA-256
  `e099204bb50e55f3e27813cd60852ccb0b1171b36168862e4d52e3f1c6ef552e`.
- Setup Authenticode status: `NotSigned`.
- Private-alpha manifest SHA-256:
  `613fe031a62709ad0c6c2d1621fd644d45d00bb325a9c8514b7673232ca80f2a`.
- Retained handoff verification: accepted, exactly six regular files.
- Setup execution during build and packaging: false.
- Microsoft Defender: installed but disabled; targeted scan not performed.
- Windows Security Center inventory: Windows Defender and Trellix Endpoint
  Security. Product presence is not claimed as a targeted scan result.
- Malware clearance, public upload, distribution, and release authorization:
  false.

The documentation-only commit recording these facts follows the handoff source
commit. The exact setup and manifest hashes above remain the identity of the
test candidate.
