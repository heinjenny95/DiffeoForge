# v101: progressive individual fitting and explicit common-model recovery

Guided fitting now keeps the current specimen after a failed fit. **Improve this
specimen** replaces the sequence-reset action. Rejection still starts one new
attempt; approval still advances to the next specimen. Existing exhausted
parameter lists can enter this recovery without resetting recorded approvals.

After the short initial common-model probes, recovery starts broad surface
matching using the aligned extent and measured mismatch. Matching width narrows
between attempts, reusing verified momentum fields on the same fixed template,
control points and deformation kernel. Four recorded capture branches and up to
ten attempts per branch bound the search; refinement stops at a width floor.
There is no total wall-clock deadline. Invalid fields start another cold branch.
**Continue saved fit** uses the current verified field and the requested number
of additional optimizer iterations; optimizer history restarts.

A source seed must have exactly one matching subject, fixed template and controls,
the same deformation kernel/control basis, bound original and working input hashes,
and finite fields of the correct dimensions. The copied seed is protected by its
hash and source receipts. Deformetrica 4.3 squeezes a singleton initial-momenta
array into two dimensions; a protected run-local `sitecustomize.py` restores only
the missing subject axis. No global runtime/package file is changed. The original
executable is retained and the scoped adapter appears in command/protection
provenance. Ordinary atlas runs and shooting commands retain their launch path.

**Saved fit searches** verifies compatible input identities and all recorded
approvals in the background. Explicit selection opens that sequence's current
checkpoint even when a later restart pointer exists. Selection performs no
calculation and does not rewrite the saved scientific evidence.

**Test denser common model** creates a separate common control grid and starts
with the current difficult specimen. Exact working targets are reused, avoiding
another mesh reduction. Earlier approvals remain in the old series and are not
transferred to the changed basis. Every specimen needs new QC; independent fields
are still only initialization for a new joint original-target confirmation.

## Verification and limits

82 unique scoped regression checks passed, including corrected test assertions.
Ruff and diff checks passed. Regression checks cover field/basis mismatches, copied-seed tampering, preservation
of approvals, continuation, finite recovery, saved-series selection, denser-grid
coverage and GUI dispatch. Actual Deformetrica 4.3 cold and warm singleton runs use
only the bundled public synthetic meshes. These check file/runtime compatibility,
not anatomical quality. The Windows package is a private development build.

More control points can increase the available deformation parameters but cannot
guarantee a useful local optimum. Sampled distances do not approve anatomy. No
private parameter analysis or private scientific run is performed for this update.
The owner's next task is visual testing of recovery and, if needed, the explicitly
separate denser basis. Installer uploads remain on explicit request.
