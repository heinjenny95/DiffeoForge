# v142 — find results by project rather than folder depth

**Open results…** opens a searchable list instead of immediately requesting an
exact run directory. It searches recent projects, explicitly added project/data
folders and previously opened results. A dataset folder can contain several
versions or a completed atlas below a selected calibration. Adding that folder
once remembers it for later sessions.

Rows show the saved project name, specimen count, date and atlas/trial category,
newest first. Explicitly named calibration/pilot/diagnostic fits are hidden until
**Include trial fits** is enabled; a small specimen count alone never determines
the category. Search also matches the underlying run ID and path. **Name result…**
assigns a local display name without renaming or moving scientific folders.
The exact location and verification note stay folded below the list.

Discovery runs outside the GUI thread and stops cooperatively when closed. It
reads bounded JSON records, skips output/geometry/cache folders, does not follow
symbolic links or Windows junctions, deduplicates overlapping roots and stops at
6,000 directories or depth 14. An incomplete or partly unavailable search is
explicitly labelled; users can add a narrower folder. No whole-disk search or
SSH connection occurs. Unknown dates are shown as unknown, with directory mtime
used only as a sorting fallback.

The per-user `result-library.json` is disposable interface state. Existing
projects, run IDs, scientific metadata, output hashes and approvals are unchanged.
A listed candidate is not a verified result or a convergence/quality claim.
Explicit selection dispatches the existing full reference/Modern result verifier;
no atlas is restarted or result silently substituted. Successfully loaded results
are remembered, including newly completed atlas results.

Source checks cover deep/overlapping paths, completed versus failed/running runs,
trial filtering, bounded/cancelled discovery, corrupt/oversized metadata, symbolic
links, persistent names/roots, explicit selection, the GUI's live timer during a
blocked worker and cancellation on close. Existing result verification and
interrupted/crashed-run routes retain their separate guards. Exact frozen and
installed behavior are separate delivery gates, as is independent first use.
