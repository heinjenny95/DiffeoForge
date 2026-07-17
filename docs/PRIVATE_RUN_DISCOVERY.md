# Private unpublished run discovery

Status: **read-only engineering safety contract; no automatic reconciliation**

A hard process termination or power loss can prevent Python cleanup and leave a
hidden Modern-workflow directory named `.NAME.tmp-UUID`. That directory is
private, unpublished state. It is not an Atlas result, even if some files look
complete.

## Exact-destination inspection

Inspect one prospective destination without changing any file:

```powershell
diffeoforge modern-private-status "C:\path\to\modern-atlas-run"
diffeoforge modern-private-status "C:\path\to\modern-atlas-run" --json
```

Exit code 0 means the destination is absent and no exact-name private candidate
was found. Exit code 1 means a published destination or private candidate makes
that target unavailable. Exit code 2 means inspection itself failed. The JSON
form follows `private-run-discovery-v0.1.json` and always records
`mutation_performed: false`.

Discovery only considers siblings matching the exact generated form
`.DESTINATION_NAME.tmp-` followed by 32 lowercase hexadecimal characters.
Similarly named directories for other destinations and malformed suffixes are
ignored. Matching symbolic links are reported and never followed.

Desktop step 3 uses the same Qt-independent service after the parameter review.
It displays the exact destination, top-level discovery status, destination
existence, and every candidate's raw status, path, and reason. A dedicated
read-only refresh button repeats the inspection. The service runs again
immediately before worker construction; a changed configuration, newly
published destination, or newly visible private candidate disables launch
without starting a child process.

## Marker and lease

Immediately after creating its private directory, `modern-run` creates:

- `.diffeoforge-private-run.json`, a versioned marker binding operation,
  absolute destination, exact private directory, UUID token, process ID,
  timestamp, and DiffeoForge version; and
- `.diffeoforge-private-run.lock`, whose first byte is exclusively locked for
  the lifetime of private computation.

The lease uses the native Windows byte-range lock or POSIX `flock`. Operating
system process teardown releases it, including after a hard process exit. The
marker and lease are removed before the final artifact inventory, verification,
and atomic rename, so neither can enter a published immutable workflow.

Before expensive Modern computation, DiffeoForge performs an exact-destination
inspection. Any pre-existing candidate blocks the new run without deleting or
rewriting that candidate. Existing destination publication remains protected by
the separate final atomic-rename check.

## Status meanings

- `active`: a valid bound marker exists and another process holds its lease.
  This proves ownership, not scientific progress, responsiveness, or health.
- `abandoned`: marker and lease are valid, but no process holds the lease.
- `unattributed`: the exact-name directory has no marker. This includes legacy
  private state and the narrow pre-marker or pre-rename crash windows.
- `invalid_metadata`: the path is not a directory or its marker/lease contract
  is malformed, mismatched, oversized, or missing.
- `indeterminate`: permissions or filesystem behavior prevented a conclusive
  non-mutating lock probe.
- `unsafe_link`: the matching path is a symbolic link; it was not followed.

Every non-clear state requires explicit human review. No status authorizes
automatic deletion, rename, resume, completion, or publication.

## Deliberate limits

The lock contract is tested on native Windows and CI Linux local filesystems.
Network shares, distributed filesystems, cloud-sync layers, backup tools, and
external software may expose different locking or timestamp behavior; an
inconclusive probe fails closed as `indeterminate`.

Two processes can still pass an initial empty scan at nearly the same instant.
Unique private directories prevent them from overwriting one another, and only
one can win the existing final atomic publication check. This slice does not
claim a global scheduler or checkpoint/resume protocol.

An explicit reconciliation policy remains separate. It must define what users
can inspect and consciously remove, preserve, or export, without ever relabeling
private state as verified output.
