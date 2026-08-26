# Portable Modern atlas execution on a server

Status: **implemented transport-neutral request, execution, and result-verification
foundation; automatic network transport and desktop orchestration remain open**

DiffeoForge can now separate the computer that prepares a Modern atlas from the
computer that performs it. The first contract deliberately does not choose a cloud
vendor or silently upload research data. It creates an immutable directory containing
the reviewed configuration, every selected mesh, optional initialization inputs, an
exact SHA-256 inventory, and explicit privacy and scientific boundaries.

The package is useful with an SSH/SFTP transfer, an institutional file-transfer tool,
an encrypted removable drive, a mounted server share, or a future DiffeoForge service.
The transfer mechanism remains outside this v0.1 contract and requires explicit user
authorization.

## Client: create and verify the request

```powershell
diffeoforge modern-remote-package `
  "C:\project\modern-atlas.yaml" `
  --output "C:\project\remote-request"

diffeoforge modern-remote-package-verify `
  "C:\project\remote-request"
```

Creation performs the same configuration, subject-count, mesh parsing, and PCA-dimension
preflight used by the Modern workflow. It copies only the selected template and subjects,
plus any declared landmarks, initial control points, or initial momenta. Absolute client
paths are replaced by package-relative paths. The packaged output path is deliberately
`.` so an accidental plain `modern-run` without an explicit destination fails before
compute instead of writing into the immutable request.

The request records the required Modern engine implementation, workflow version,
CPU/CUDA device, float64 precision, source configuration hash, mesh metadata, and every
file hash. A CUDA request can be prepared on a CPU-only client; availability is checked
fail-closed on the execution host.

The v0.1 request does not package an existing optimizer resume state. A crash during
server execution retains the Modern workflow's private checkpoint state on that server,
where the existing checkpoint-recovery workflow can create an immutable successor.
Automatic cross-host recovery and job migration remain later work.

## Server: verify and execute

After an explicitly authorized transfer, run on the server:

```powershell
diffeoforge modern-remote-package-verify `
  "D:\jobs\remote-request"

diffeoforge modern-remote-run `
  "D:\jobs\remote-request" `
  --output "D:\results\atlas-001"
```

`modern-remote-run` reverifies the complete package before allocating the atlas, requires
the exact requested engine implementation, requires the requested device to be available,
uses the existing immutable Modern workflow and progress events, and performs no CPU
fallback for a CUDA request. The result must be outside the request package. A successful
command finishes only after the complete workflow and nested atlas/PCA bundle verify and
the result binds back to the request.

## Client: verify the returned result

After downloading or otherwise retrieving the result directory:

```powershell
diffeoforge modern-remote-result-verify `
  "C:\project\remote-request" `
  "C:\project\downloaded-atlas-001"
```

This rechecks the request, the result's exact inventory, every workflow and nested bundle
hash, the packaged and effective configurations, engine/device identity, subject order,
filenames, mesh counts, and mesh hashes. It does not trust a result merely because it came
from the expected server path.

## Privacy, trust, and cost boundary

- The request contains raw surface meshes and specimen filenames. Creating it is not
  consent to transfer it.
- DiffeoForge v0.1 performs no upload, download, authentication, telemetry, billing, or
  server discovery.
- Hash verification detects changed bytes; it does not prove that a server kept private
  copies confidential or deleted them.
- A future managed transport must add authenticated endpoints, encrypted transfer,
  explicit destination/account review, quotas and cost estimates, resumable chunking,
  retention/deletion controls, and an append-only remote job lifecycle without weakening
  this request/result binding.
- Numerical convergence and a verified download remain separate from reconstruction QC,
  sensitivity analysis, and biological interpretation.

## Next server slices

1. Version an authenticated remote job lifecycle with queued/running/checkpointed/
   completed/failed/cancelled states and reconnectable progress cursors.
2. Add resumable content-addressed upload so unchanged mesh bytes are not retransmitted.
3. Publish signed or mutually authenticated result descriptors before download.
4. Add the server choice to desktop project review with visible privacy, retention, cost,
   and expected-runtime controls.
5. Qualify one institutional Linux/CUDA deployment independently from the current Windows
   RTX 4080 evidence.
