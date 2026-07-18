# Inno Setup ISSigTool signature evidence

This developer-only workflow records the third official Inno Setup download
verification method. It executes an independently authenticated
`ISSigTool.exe` only to read and verify the signature of the exact pinned
installer. It never executes the installer.

The machine boundary is
`distribution/windows/inno-signature-evidence-contract-v0.1.json`.

## Pinned trust chain

- installer: `innosetup-7.0.2-x64.exe`, 17,020,192 bytes, SHA-256
  `5ad54ca3def786f8f4212552e54cc6d8d61329e2d24a1cfee0571d42c2684ff1`;
- detached signature: `innosetup-7.0.2-x64.exe.issig`, 380 bytes, SHA-256
  `b85f4a9c527ee573d308840e859ff3ca99c8a750acb259d51f111301c7ef71bd`,
  release-attested with the explicit tag `is-7_0_2`;
- verifier: `ISSigTool.exe`, 919,184 bytes, SHA-256
  `aea490d45665a88c0c832d25647d21c1b87962efedb25668caec05678e0fd7c6`,
  release-attested with the explicit tag `is-6_7_3` and Authenticode-valid
  for `Pyrsys B.V.`; and
- public key: `def02.ispublickey`, 248 bytes, SHA-256
  `32bea6bceb4ac7c4e6b3becdf3fb38de77378c5e76d494ab907d87cfab9e597b`,
  reconstructed from Git blob `ab717206d876bd9d63a9bbb16bcf0e5f6928af73`
  at commit `c25dc6479cdc3be28e682a025fcf60765bba3de0`. The annotated release tag
  object `d2509df69f828a7148294e29b2ca252c3250210c` must be reported by GitHub
  as a valid signature over that commit.

The official commands are release-specific:

```powershell
gh release verify-asset is-6_7_3 C:\exact\ISSigTool.exe `
  --repo jrsoftware/issrc --format json
gh release verify-asset is-7_0_2 C:\exact\innosetup-7.0.2-x64.exe.issig `
  --repo jrsoftware/issrc --format json
ISSigTool.exe --key-file=C:\exact\def02.ispublickey verify `
  C:\exact\innosetup-7.0.2-x64.exe
```

Omitting either positional release tag resolves the latest release and is not
accepted. The generic `gh attestation verify` command is not interchangeable
with `gh release verify-asset`.

## Two-phase observation

Place the matching `.issig` file beside the installer. Keep the verifier and
public key outside both the repository and the new empty output directory.
From an exact clean source commit, run on 64-bit Windows:

```powershell
powershell -NoProfile -File tools\observe_inno_signature.ps1 `
  -Installer C:\exact\innosetup-7.0.2-x64.exe `
  -Signature C:\exact\innosetup-7.0.2-x64.exe.issig `
  -PublicKey C:\exact-key\def02.ispublickey `
  -SignatureTool C:\exact-tool\ISSigTool.exe `
  -ProjectFile C:\source\DiffeoForge\pyproject.toml `
  -OutputDirectory C:\new-empty\inno-signature-evidence `
  -SourceCommit <40-lowercase-hex> `
  -Python C:\source\DiffeoForge\.venv\Scripts\python.exe `
  -GitHub "C:\Program Files\GitHub CLI\gh.exe"
```

The wrapper first creates exactly eight prerequisite observations. The Python
preflight validates all input bytes, both release attestations, the verifier's
Authenticode signer, the signed tag object, the exact public-key content, all
GitHub CLI command vectors, the clean source binding, and the output boundary.
Only a successful preflight permits the one scoped `ISSigTool` invocation.

The ninth raw observation records its exact three-element command, exit code,
single `: OK` output line, and all four input hashes immediately before and
after execution. The wrapper then writes canonical evidence and its sidecar.
All eleven files are non-overwriting.

## Offline verification

Retain the evidence SHA-256 independently, then run:

```powershell
python tools/inno_signature_evidence.py verify `
  C:\evidence\inno-signature-evidence.json `
  --expect-evidence-sha256 <64-lowercase-hex>
```

Offline verification reconstructs the canonical evidence from every retained
raw file and every still-available input. It does not repeat GitHub's network
verification or the ECDSA operation, so the external evidence digest remains a
required trust input.

## Explicit boundary

The accepted observation proves one exact verifier operation with exit code 0
and the exact success line. It leaves both `installer_execution_authorized` and
`execution_authorized` false. It does not authorize installer execution,
installation, compilation, redistribution, release, or any numerical,
security, scientific, or production-suitability claim.

Official references:

- <https://jrsoftware.org/isdl-verify.php>
- <https://github.com/jrsoftware/issrc/releases/tag/is-6_7_3>
- <https://github.com/jrsoftware/issrc/releases/tag/is-7_0_2>
