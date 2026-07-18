# Same-owner local Windows private-alpha handoff

Status: **implemented packaging contract; first exact handoff pending**

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
