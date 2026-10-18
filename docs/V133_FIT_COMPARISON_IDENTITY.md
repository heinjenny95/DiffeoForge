# v133 — explicit saved/current fit identity

Fit inspection now labels the current attempt as well as the selected saved
attempt. **Best so far** remains the human-selected starting point; it can be
older than the immediately preceding attempt. **Previous attempt** refers to
the preceding eligible saved fit for the same specimen.

Surface delivery must match the displayed current/reference selection and the
current inspection's loaded file identities. A late delivery cannot be relabeled
as a newly selected saved fit. Comparing the current attempt or reconstruction
file with itself is rejected, the saved view is cleared, and decisions remain
unavailable. Separate runs that export byte-identical surfaces remain valid
comparisons and receive an explicit identical-surfaces message.

The current mesh objects are retained across reference changes. Native fitting,
initialization, saved best preferences and anatomical approval rules are unchanged.
No historical decision or research result is rewritten.

The reported intermittent duplicate display was not reproduced in the inspected
recent comparison: its saved and current reconstructions had different file
hashes and geometry. These changes clarify identity and guard against incorrect
surface delivery; they do not claim that every visually similar pair indicates
an application error or that all unobserved cases have been reproduced.

Verification covers delayed deliveries, self-file rejection, distinct rendered
geometry, legitimate identical exports and preservation of the shared current
view. A read-only inspection of retained native public-fixture results verifies
selected file paths/hashes through repeated and rapid reference changes, visible
attempt labels at minimum/ordinary sizes, no QC write and no new native job.
Source, tested build, installed runtime and installer distribution are separate;
installation waits for the owner's application and scientific workers to be idle.

All 52 distinct targeted regression cases pass, including six new comparison
identity/rendering cases. Version/repository contracts, Ruff and diff checks
pass. Exact-product frozen inspection also passed with the product PYZ, actual
runtime and four matching worker executables: selected paths/hashes, repeated
and rapid switching, current geometry reuse and minimum/ordinary-size labels.
All source fixture files were preserved, with no QC write or new native job.

The five-executable Windows bundle, startup/worker/preparation checks, dependency
metadata, SBOM and complete installer build verification passed. The tested
installer is staged locally. Installed remains v132 because the owner's GUI and
scientific worker were still active at the final readiness check. Normal saved
owner close, verified backup, fresh idle guards and installed verification remain
required. No installer upload, research rerun or approval change occurred.
