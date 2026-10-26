# Archiving inactive build working copies

The owner authorizes NAS archiving when local storage is low. This concerns
explicitly selected inactive packaging working copies. Installed runtimes, current
deliveries, active jobs and scientific input/field dependencies remain protected.
Private network locations and archive inventories belong in the owner's local
handoff and archive, never in this public repository.

Before copying, resolve each selected source to its exact allowed parent/name,
reject links or reparse directories, and check for live processes using it. Record
the complete relative file and directory sets, file sizes, SHA-256 values and
original restoration paths. Include hidden files and empty directories.

Copy the directory tree into a new owner-selected NAS archive without move/purge
flags. Independently hash every destination file and compare the entire file set
with the frozen manifest. Rehash the source too, rejecting concurrent changes.
Store the manifest and verification receipt both locally and on the NAS before
removing an original working copy. Check the resolved source boundary and live
processes again immediately before a literal-path local removal.

Keep a local restoration index and per-folder pointer. Restoration copies a chosen
archive back to its recorded original location and compares all hashes; do not
blindly overlay an existing directory or infer permission to restart a computation.
An unavailable destination or failed check retains the unverified local copy.
Completed earlier folders remain recoverable from their independently verified
archives and receipts if a later folder fails.

Synthetic guard checks cover same-size byte corruption, an unexpected destination
file, an out-of-scope source and an excluded current build. Actual archive receipts
separately bind every copied file and unchanged source. These are storage checks,
not scientific qualification, a software installation or installer distribution.
