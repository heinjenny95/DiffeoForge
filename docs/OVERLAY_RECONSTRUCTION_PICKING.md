# Mark reconstructed material in an overlay

The correction editor can display the original surface and a reconstruction
wireframe while directing red clicks to the reconstruction. Previously, clicks
were first tested against the original's reduced display surface. Reconstructed
material inside an original opening was therefore silently unpickable in an
overlay, even though the reconstruction's exact ray intersection was valid.
Fit-only view used the reconstruction for both checks and provided a workaround.

The canvas now receives the active displayed picking layer separately from its
base model. Overlay reconstruction clicks first intersect the bounded displayed
reconstruction geometry, then use the existing exact reconstruction picker and
ray bounds. The camera and scientific geometry remain unchanged. Original full
detail does not bypass the reconstruction preview check, because the overlay
still draws its own preview. Missing or undrawable active previews reject clicks
instead of silently falling back to the original.

Saved points retain the inspected reconstruction hash and exact material-face
binding. Empty-space clicks, hidden material behind a preview opening and green
original-surface protection keep their existing meaning. Normal landmark and
correspondence viewers default to their original displayed model. Picking-layer
identity is part of the settled-view key and changing models cancels pending
picks.

The new Qt journeys use real mouse events, the production preview loader and
the exact geometry locator. They verify visible purple pixels before clicking
reconstruction material inside an original opening, preview/full-detail modes,
save/reopen, source switching and rejected misses. Earlier editor tests called
the post-pick handler directly and did not exercise this failing viewport gate.
These checks do not establish anatomical fit quality or qualify a new installer.

Delivery remains separate: the source fix does not replace an installed runtime
or interrupt an active pilot. The current workaround is to select Fit while
marking reconstructed material until the next tested runtime is installed.
