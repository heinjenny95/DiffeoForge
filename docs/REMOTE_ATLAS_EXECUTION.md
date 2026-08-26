# Authenticated Modern atlas execution on a server

Status: **implemented private single-operator HTTP(S) service, CLI, and persistent
desktop controller; managed deployment and visible desktop controls remain open**

DiffeoForge can prepare a reviewed Modern atlas on one computer, execute it on a
compatible CPU/CUDA server, reconnect to progress, cancel it cooperatively, and
download a result that is cryptographically bound to the exact request. The transport
is vendor-neutral and does not silently select a server, account, retention period, or
billing plan.

This v0.1 service is intended for one trusted research operator or one trusted team
inside an institutional security boundary. It is not a public multi-tenant service.

## Server installation boundary

Install the same reviewed DiffeoForge source revision and the Modern dependencies on the
execution host before starting the service:

```powershell
python -m venv .venv-server
.\.venv-server\Scripts\python.exe -m pip install ".[modern-engine]"
```

On Linux, use `.venv-server/bin/python` and `.venv-server/bin/pip`. A CUDA request
also requires a server-side PyTorch/CUDA installation that passes DiffeoForge's exact
CUDA/float64 preflight. The repository does not currently publish a qualified Modern
CUDA server image; selecting a driver, PyTorch build, GPU host, and provider is an
explicit deployment decision.

## 1. Prepare the exact request

```powershell
diffeoforge modern-remote-package `
  "C:\project\modern-atlas.yaml" `
  --output "C:\project\remote-request"

diffeoforge modern-remote-package-verify `
  "C:\project\remote-request"
```

Creation performs the same configuration, subject-count, mesh parsing, and PCA-dimension
preflight used by the Modern workflow. It copies only selected inputs and replaces
absolute client paths with package-relative paths. The request records the required
engine implementation, workflow version, CPU/CUDA device, float64 precision, subject
order, mesh metadata, and an exact SHA-256 inventory.

A CUDA request can be prepared on a CPU-only client. CUDA availability is checked
fail-closed on the execution host; there is no silent CPU fallback.

## 2. Create the shared secret once

Create the token file on a trusted machine and transfer one private copy to each
authorized client through an independently secured mechanism:

```powershell
diffeoforge modern-remote-token-init "D:\DiffeoForgeServer\server.token"
```

The token is high entropy and is never printed by DiffeoForge. Keep it outside Git,
project exports, logs, and diagnostic bundles. The current protocol uses one bearer
token for the complete private service; it does not yet provide per-user identities,
scopes, revocation lists, or audit attribution.

## 3. Start the persistent service

The safe default listens only on loopback:

```powershell
diffeoforge modern-remote-server `
  --root "D:\DiffeoForgeServer" `
  --token-file "D:\DiffeoForgeServer\server.token" `
  --workers 1
```

The root stores verified requests, state, append-only progress events, private workflow
state, and completed result archives. It must be on storage available only to the server
operator. `--workers` bounds simultaneous executions; `--max-active-jobs` and
`--max-upload-bytes` bound queue and upload admission.

For a remote server, use either:

- an authenticated SSH tunnel to the default loopback listener; or
- an HTTPS listener with an explicit certificate and private key.

Example HTTPS listener:

```powershell
diffeoforge modern-remote-server `
  --root "D:\DiffeoForgeServer" `
  --token-file "D:\DiffeoForgeServer\server.token" `
  --host 0.0.0.0 `
  --port 8787 `
  --tls-certificate "D:\DiffeoForgeServer\tls\server.crt" `
  --tls-private-key "D:\DiffeoForgeServer\tls\server.key"
```

DiffeoForge refuses a non-loopback plain-HTTP bind. Certificate provisioning, DNS,
firewall rules, OS service supervision, and GPU/CUDA installation belong to the chosen
institutional or cloud environment and are not silently configured by this command.

## 4. Submit, reconnect, download, and delete

```powershell
$server = "https://atlas.example.edu:8787"
$token = "C:\private\diffeoforge-server.token"
$ca = "C:\private\institution-ca.pem"

diffeoforge modern-remote-submit `
  "C:\project\remote-request" `
  --server $server --token-file $token --ca-file $ca

diffeoforge modern-remote-status JOB_ID `
  --events --limit 100 --server $server --token-file $token --ca-file $ca

diffeoforge modern-remote-wait JOB_ID `
  --download "C:\project\downloaded-atlas-001" `
  --job-directory "C:\project\remote-request" `
  --server $server --token-file $token --ca-file $ca
```

`modern-remote-submit` prints a random 32-character submission ID before network
transfer and reverifies the request before upload. The server uses that ID as the job ID
and binds it permanently to the exact archive hash. If the connection fails after an
uncertain acceptance, repeat the command with `--submission-id PRINTED_ID`: the same
request returns the existing job, while different bytes fail with a conflict instead of
starting duplicate expensive work.

The server streams the
archive to bounded storage, checks its declared length and archive hash, safely extracts
it without accepting traversal, links, duplicate entries, encryption, or unbounded
expansion, and then reverifies the complete request before queueing it.

`modern-remote-status --events` returns a bounded event page and reports whether more
pages remain. `modern-remote-wait` drains those reconnectable pages automatically.
Stopping the local wait with
Ctrl+C does not cancel computation. Cancellation is always explicit:

```powershell
diffeoforge modern-remote-cancel JOB_ID `
  --server $server --token-file $token --ca-file $ca
```

Cancellation is cooperative and can take until the running numerical operation reaches
its next cancellation check. A queued job is cancelled without starting it.

After verification and any required scientific/QC review, delete terminal server data
explicitly:

```powershell
diffeoforge modern-remote-delete JOB_ID `
  --server $server --token-file $token --ca-file $ca
```

There is deliberately no automatic retention duration in v0.1. Active jobs cannot be
deleted. Completed, failed, cancelled, or interrupted jobs remain until this authenticated
delete request or an independently governed server-side retention procedure removes them.

## Persistence and restart behavior

- Queued jobs survive a clean or unclean service restart and return to the queue.
- A job recorded as `running` or `cancel_requested` becomes `interrupted` after restart.
  It is never silently rerun, because doing so could duplicate expensive computation.
- Existing private Modern checkpoints remain in the server job directory for an explicit,
  operator-reviewed recovery path. Automatic remote recovery and job migration are not
  yet implemented.
- Completed results are reverified when persistent state is loaded.

The current worker executes the Modern workflow inside the server process. A fatal native
or GPU failure can therefore stop the service; persistent state then applies the
fail-closed interrupted behavior above. Per-job process isolation is a later production
hardening step.

## Desktop persistence foundation

The Qt-independent desktop controller creates a local session directory before upload.
It contains the exact portable request, server URL, client-generated job ID, reconnectable
event cursor, destination binding, and mutable remote status. It never stores the bearer
token. If the application or network stops after submission, a new controller can reopen
that directory with an explicitly supplied token file, resume event polling, and download
the request-bound result. Closing a client is therefore not equivalent to cancelling a
server job.

The public desktop screens do not yet expose server URL, token/CA selection, privacy
authorization, or session reopening; this controller is the tested non-Qt layer for that
next UI slice.

## Result trust and scientific boundary

Every download is streamed with a size limit and archive-hash check, safely extracted,
and verified against the original local request. Verification covers the exact inventory,
nested workflow and atlas/PCA bundles, effective configuration, engine/device identity,
subject order, filenames, mesh counts, and mesh hashes. Archive hashes provide integrity,
not proof that the server kept no private copy.

Transport success and numerical convergence do not establish reconstruction quality,
parameter suitability, sensitivity, PCA stability, or biological validity. The passing
Modern Engine 236-subject gates remain cohort-, protocol-, and hardware-specific.

## Remaining production layers

1. Qualify and document one institutional Linux/CUDA deployment.
2. Isolate each running job in a supervised process and expose explicit checkpoint recovery.
3. Add per-user authentication, scoped authorization, audit logging, rate limiting, and
   governed automatic retention for a multi-user service.
4. Add resumable content-addressed upload and download for large cohorts.
5. Expose the persistent desktop controller through reviewed server selection, privacy,
   expected-runtime, retention, and cost controls in the desktop application.
