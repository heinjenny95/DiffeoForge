# v143 — shared visualization views and comparison

Changing the anatomical view previously updated only the PCA glyphs. SD panels,
maps and movies continued to show the earlier cameras. The preview also created
a new offscreen renderer for every input, delaying each small turn.

**Mesh view… → Apply to all visualizations** now prepares a complete, separately
inventoried presentation bundle. PCA glyphs, mean/SD panels, displacement and
signed-normal maps, movies, inline SD previews and matching method 3D viewers use
the chosen view. Six-view panels/movies start with the chosen view and retain five
opposing/orthogonal perspectives in that same basis. The original atlas, PCA,
geometry, native samples, displacement measurements, scales and approvals remain
unchanged. Already-computed, verified native movie samples are reused; a camera
change never executes Shooting or an optimizer.

The previous complete bundle stays visible during background preparation. The
new bundle replaces it only after every medium verifies. Current-media and ZIP
exports use that complete bundle; export is disabled while a view is pending.
Named views remain bound to the original media identity. Cancellation, source
changes or rendering failures cannot publish a partial view or save its selection.

The preview keeps one renderer and specimen surface warm on a dedicated thread.
Its bounded mailbox replaces pending input with the latest rotation, while
showing completed intermediate frames during continuous movement. A 16 ms input
timer does not restart on every drag event. Full-media rendering cannot occupy
the preview worker; closing the dialog does not wait for renderer teardown.

Hovering a specimen mesh shows its saved ID and scores in the 2D and 3D PCA views.
3D picking follows visible image pixels and draw order, including glyphs larger
than the old centre-only hit area. Offline gallery hover uses the same labels.

The PCA pair, SD, heatmap and movie selectors retain individual items and add an
**All · side by side** option. PCA pairs include PC1/PC2, PC1/PC3 and PC2/PC3 when
available. Image overviews support zoom/pan and PNG/JPEG snapshots. Movie
comparison has common play/pause, seeking and a shared playback clock; it can
export a combined MP4 with a checked common frame count/rate. Individual files
and the gallery ZIP remain available. The offline gallery also offers comparison
layout and common movie playback. These views show computed results, not a new
scientific analysis or anatomical approval.

## Verification gates

Focused source checks cover continuous preview input, bounded warm-renderer
reuse, non-blocking close, atomic/cancelled complete-media publication, visible
specimen picking, individual/all selections, offline labels, synchronized video
export and preserved originals. A complete synthetic renderer test exercises
all figures and movies, rejects scientific execution during a camera change,
checks exact scores/common scales and verifies the presentation ZIP allowlist.
Existing mesh-view, method, media, result-opening and handoff regressions remain
applicable. Frozen runtime, installation and independent first use are separate
delivery gates; source tests alone do not establish them.
