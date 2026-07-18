# Inno Setup toolchain authenticity evidence

Status: **implemented authenticity observation; downloaded installer execution
and compiler execution remain unauthorized**

This workflow observes the exact Inno Setup 7.0.2 x64 installer selected by
[ADR 0006](decisions/0006-reproducible-windows-installer-contract.md). It is a
pre-execution gate for a future compiler environment, not an installer build.
The exact machine boundary is
`distribution/windows/inno-toolchain-evidence-contract-v0.1.json`.

## Required asset identity

- repository and immutable release: `jrsoftware/issrc`, tag `is-7_0_2`;
- release database ID: `352994135`;
- signed tag-object SHA-1: `d2509df69f828a7148294e29b2ca252c3250210c`;
- release asset ID: `475225237`;
- file: `innosetup-7.0.2-x64.exe`, 17,020,192 bytes; and
- SHA-256:
  `5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1`.

The official release-specific verification command is:

```powershell
gh release verify-asset is-7_0_2 C:\exact\innosetup-7.0.2-x64.exe `
  --repo jrsoftware/issrc --format json
```

The positional tag is mandatory: without it, GitHub CLI resolves whichever
release is latest at observation time. The generic `gh attestation verify`
command is also not interchangeable with this release-attestation command. The
observer validates the returned DSSE payload,
verified statement, repository, IDs, tag, signed tag-object digest, predicate,
attester identity, timestamp authority, asset name, and asset digest instead
of trusting exit code alone.

Windows Authenticode must independently report `Valid` with signer subject
`CN=Pyrsys B.V., O=Pyrsys B.V., S=Noord-Holland, C=NL` and a timestamp
certificate. The concrete leaf and timestamp thumbprints are recorded, not
pinned, so legitimate certificate rotation does not silently rewrite the
publisher identity contract.

## Make one observation

Use a pre-downloaded asset and a new empty output directory outside the source
repository and asset directory. Run from a clean reviewed DiffeoForge source
commit with the source environment active:

```powershell
powershell -NoProfile -File tools\observe_inno_toolchain.ps1 `
  -Asset C:\exact\innosetup-7.0.2-x64.exe `
  -ProjectFile C:\source\DiffeoForge\pyproject.toml `
  -OutputDirectory C:\new-empty\inno-authenticity-evidence `
  -SourceCommit <40-lowercase-hex> `
  -Python C:\source\DiffeoForge\.venv\Scripts\python.exe `
  -GitHub "C:\Program Files\GitHub CLI\gh.exe"
```

The wrapper reads but never starts the downloaded asset. It writes exactly:

- `inno-release-attestation.json`;
- `inno-authenticode-observation.json`;
- `inno-release-verifier-observation.json`;
- `inno-toolchain-evidence.json`; and
- `inno-toolchain-evidence.sha256`.

The raw verifier record binds the exact `gh.exe` path, bytes, SHA-256, reported
version, eight-element command vector including the pinned tag, and zero exit
code. The canonical
evidence additionally binds its source commit, DiffeoForge version, project,
machine contract, observation wrapper, asset, all three raw files, certificate
observations, and missing gates. Every file is non-overwriting; symbolic paths,
junctions, extra files, altered bindings, wrong identity, wrong publisher, or
malformed observations fail closed.

## Offline re-verification

Retain the evidence SHA-256 independently, then run:

```powershell
python tools/inno_toolchain_evidence.py verify `
  C:\evidence\inno-toolchain-evidence.json `
  --expect-evidence-sha256 <64-lowercase-hex>
```

Offline verification reconstructs all recorded source, asset, raw-output,
certificate, verifier, and canonical-JSON bindings. It does not
cryptographically repeat GitHub's network-backed release verification; that
successful operation is a recorded observation tied to the exact verifier
binary and output.

## What remains forbidden

This evidence leaves `execution_authorized: false`. It does not authorize or
perform installation of Inno Setup, `ISCC.exe` compilation, installer upload,
license or redistribution approval, DiffeoForge code signing, clean-VM
install/uninstall, Defender or no-network observation, project-preservation
testing, numerical validation, scientific validation, or a production claim.
The third official Inno Setup Signature Tool method is also retained as a
separate later gate rather than silently inferred from the other observations.

Primary references:

- [Official Inno Setup download verification](https://jrsoftware.org/isdl-verify.php)
- [Official immutable Inno Setup 7.0.2 release](https://github.com/jrsoftware/issrc/releases/tag/is-7_0_2)
