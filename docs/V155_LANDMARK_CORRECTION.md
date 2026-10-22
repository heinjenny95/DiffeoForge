# v155 — correct existing landmarks on selected specimens

Step 1 adds **Correct/change existing landmarks…** beneath the landmark file
controls. It uses the CSV currently selected in the Landmarks field, rather than
requiring an autosaved placement draft. A searchable checkbox list permits one,
several or all meshes from the current cohort, including the template if needed.
Preparation reads the full existing table and verifies selected original meshes
in a background task; only the chosen specimens enter the correction editor.

Existing labels and coordinates appear immediately. Choose a label and click its
new original-surface position; clear and undo remain available. Label addition,
renaming and removal are hidden in correction mode so that subset editing cannot
change cohort-wide homology. Automatic specimen advancement defaults off. The
normal new-placement editor retains its existing behavior.

Save merges edited positions into a complete Float64 cohort CSV in a separate
project-local correction folder. Every other coordinate is retained exactly; the
source CSV, meshes, existing alignments and fits are preserved. A source-bound
receipt records the selected/changed specimens and output hash. The main window
uses the new CSV only after successful saving and clears the previous input/GPA
review. A fresh alignment review is required; no alignment or fit starts here.
GPA may change the transforms of other specimens even though their points stay
unchanged. Existing pilot results remain historical results of their old inputs.

Correction preparation and saving run outside the GUI thread, with repeat-click
guards. Source CSV/selected mesh changes, mismatched labels, unselected specimen
injection and non-finite coordinates prevent publication. Correction drafts bind
to the source CSV, selected meshes and ordered cohort; Cancel retains an actual
edited draft for the same selection. Saving creates a separate file and does not
overwrite the original. Corrections remain anatomical decisions made by the user.

Focused tests cover exact subset merging, single/multiple selection, source
tampering, invalid coordinates/labels, draft resume, original-surface picking,
the actual main-button-to-save route and versioned installer names. Synthetic
source and exact runtime probes cover real mouse clicks and retained pilot/review
behavior with native dispatch forbidden. See [delivery state](V155_DELIVERY.md).
