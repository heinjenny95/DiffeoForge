# ADR 0009: Private authenticated remote-atlas service

- Status: accepted
- Date: 2026-08-26

## Context

Portable Modern atlas request and result directories already separate preparation from
execution, preserve exact input identity, and allow manual SSH/SFTP or institutional
transfer. They do not provide a reconnectable job lifecycle. A large atlas should run on
a suitable server without requiring the desktop client to remain connected, without
silently falling back to local compute, and without weakening request/result verification.

Research meshes and specimen filenames are sensitive. Selecting a cloud provider,
retention duration, account, billing limit, or public exposure without an explicit
operator decision would exceed the transport contract.

## Decision

DiffeoForge provides a vendor-neutral v1 HTTP(S) API and CLI for a private,
single-operator Modern atlas service:

- one high-entropy bearer token authenticates all job operations;
- plain HTTP is accepted only on loopback, enabling a separately authenticated SSH
  tunnel; every non-loopback bind requires an explicit TLS certificate and key;
- uploads and downloads stream with byte limits and exact archive hashes;
- archive extraction rejects traversal, symbolic entries, duplicates, encryption,
  unsupported compression, and configured expansion limits;
- the server reverifies a request before queueing it and the client reverifies every
  downloaded result against its local request;
- server state and append-only progress events persist below an operator-selected root;
- worker, active-job, upload, file-count, and unpacked-byte bounds are explicit;
- queued jobs are requeued after restart, while formerly running jobs become
  `interrupted` and are never automatically duplicated;
- cancellation is cooperative and server-side deletion is authenticated, explicit, and
  limited to terminal jobs.

The initial runner executes jobs inside the service process. The portable directory
contract and manual `modern-remote-run` path remain supported independently of the
network service.

## Consequences

A researcher can operate an atlas on a separately provisioned CPU/CUDA host using only
DiffeoForge CLI commands, reconnect after a client interruption, and retrieve a result
whose identity is bound to the reviewed request. No cloud vendor or proprietary queue is
required.

This service is not a public or multi-tenant boundary. It does not yet provide per-user
authorization, audit identity, token rotation, rate limiting, automatic retention,
resumable content-addressed transfer, cost controls, process-level job isolation,
automatic checkpoint recovery, service installation, or infrastructure provisioning.
Those require separate deployment and governance decisions. The endpoint operator remains
responsible for certificates, firewalling, storage confidentiality, backups, CUDA/runtime
qualification, and deletion policy.

## Rejected alternatives

- Silently selecting and provisioning one cloud vendor would couple scientific workflow
  semantics to account, billing, privacy, and residency choices outside this repository.
- Accepting plain HTTP on a remote interface would expose both bearer credentials and raw
  meshes to network interception.
- Automatically rerunning an in-progress job after service restart could duplicate costly
  GPU work and publish ambiguous successor state.
- Treating an archive checksum as server attestation would confuse transfer integrity with
  confidentiality, execution trust, or scientific validity.
