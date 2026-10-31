# Archiving inactive builds and owner-selected data

The owner authorizes NAS archiving when local storage is low. This concerns
explicitly selected inactive packaging working copies and owner-selected data.
Installed runtimes, current deliveries, active jobs and scientific input/field
dependencies remain protected.
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

If final summary aggregation fails after every folder has completed, retain that
error and reconstruct only the report from the immutable per-folder manifests
and verified completion receipts. Do not repeat transfers or removals to recreate
a missing summary. Final archive/restoration checks must still pass independently.

Synthetic guard checks cover same-size byte corruption, an unexpected destination
file, an out-of-scope source, protected-root overlap, long Windows paths and
hardlinked files. Actual archive receipts separately bind every copied file and
unchanged source. These are storage checks, not scientific qualification, a
software installation or installer distribution.

## Datasets and exact file selections

Resolve the current run's dependencies from its manifests before selecting older
work for archiving. A latest result can still require older prefix fields, native
inputs and complete output inventories. Keep that dependency closure local;
directory age alone does not establish that a run is inactive. Preserve current
deliveries, landmark corrections, meshes, segmentations and checkpoints outside
the owner's explicit selection. Check both application and native/backend use,
including alternative path spellings used by local virtual machines.

A complete-tree manifest binds every relative file and directory under its exact
root. When only CT stack files or other individual leaves are selected, freeze
their exact relative paths instead. Record each selected file's size, SHA-256 and
source identity; use actual Windows file IDs rather than cached directory-entry
IDs. Verify destination bytes against that selection and recheck unchanged source
bytes and identities before literal-path removal. Mixed-content parent folders
remain in place; never recursively remove them to archive selected leaves.

Record original restoration paths for both forms of selection and preserve an
inventory of unselected sibling data. Maintain per-unit verification and completion
receipts so a later failure does not obscure earlier completed transfers. A partial
archive is not a completed batch: restore only verified units and retain unverified
local data. Restoring an archived dependency does not authorize restarting its run.
