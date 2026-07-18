# Portable Inno toolchain and compiler-probe evidence

This developer-only workflow records one bounded execution of the authenticated
Inno Setup 7.0.2 x64 installer in official portable mode and one compilation of
a fixed payload-free probe. It proves that the selected bytes can prepare the
expected compiler inventory on the observed Windows host. It does not build or
authorize distribution of a DiffeoForge installer.

## Trust and execution boundary

The wrapper fails closed unless both earlier evidence documents reconstruct
successfully with externally supplied SHA-256 values and bind the same exact
installer. It then requires a clean, exact source commit and three distinct,
empty, real directories outside the repository and input directories.

Only after that preflight succeeds may the wrapper:

1. execute the exact `innosetup-7.0.2-x64.exe` bytes with the ten arguments
   pinned by
   `distribution/windows/inno-portable-toolchain-evidence-contract-v0.1.json`;
2. record and hash the complete portable inventory and install log;
3. require valid Pyrsys Authenticode observations for `ISCC.exe`,
   `ISCmplr.dll`, `ISPP.dll`, and the installed `ISSigTool.exe`; and
4. execute `ISCC.exe` once against
   `distribution/windows/InnoCompilerProbe.iss`.

The probe uses `CreateAppDir=no`, `Uninstallable=no`, and `Output=no`. It has no
application files, registry changes, shortcuts, or run actions. The compiled
probe is transient evidence, not a distributable product.

## Windows observation

Prepare three new empty directories. Keep the prior toolchain-authenticity and
ISSigTool-signature evidence directories intact, including their sidecars and
raw observations. From an exact clean checkout, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\observe_inno_portable_toolchain.ps1 `
  -Installer C:\absolute\input\innosetup-7.0.2-x64.exe `
  -ToolchainEvidence C:\absolute\toolchain-evidence\inno-toolchain-evidence.json `
  -ExpectedToolchainEvidenceSha256 <64-lowercase-hex> `
  -SignatureEvidence C:\absolute\signature-evidence\inno-signature-evidence.json `
  -ExpectedSignatureEvidenceSha256 <64-lowercase-hex> `
  -ProjectFile C:\absolute\DiffeoForge\pyproject.toml `
  -ToolchainDirectory C:\absolute\new-empty-toolchain `
  -ProbeOutputDirectory C:\absolute\new-empty-probe-output `
  -EvidenceOutputDirectory C:\absolute\new-empty-evidence `
  -SourceCommit <40-lowercase-hex> `
  -Python C:\absolute\DiffeoForge\.venv\Scripts\python.exe
```

The exact evidence boundary contains four raw files plus canonical evidence and
its sidecar. Existing files are never overwritten:

- `inno-portable-install.log`
- `inno-portable-install-observation.json`
- `inno-portable-authenticode-observation.json`
- `inno-compiler-probe-observation.json`
- `inno-portable-toolchain-evidence.json`
- `inno-portable-toolchain-evidence.sha256`

## Offline reconstruction

Retain every referenced input, prerequisite evidence directory, portable
toolchain file, probe output, and raw observation. Reconstruct all available
bindings without executing the installer or compiler:

```powershell
python tools\inno_portable_toolchain_evidence.py verify `
  C:\absolute\evidence\inno-portable-toolchain-evidence.json `
  --expect-evidence-sha256 <64-lowercase-hex>
```

The externally supplied digest is intentional: a sidecar stored next to altered
evidence is not an independent trust anchor.

## Explicit nonclaims

This slice does not establish bit-for-bit deterministic compiler output, a
system-wide Inno Setup installation, license compatibility, redistribution
approval, DiffeoForge output signing, clean-VM behavior, Defender status,
network isolation, numerical correctness, scientific validity, or production
suitability. Those remain separate release gates.

Official references:

- [Inno Setup command-line parameters](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)
- [Inno Setup miscellaneous notes (`/PORTABLE=1`)](https://jrsoftware.org/ishelp/topic_technotes.htm)
- [Inno Setup command-line compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)
