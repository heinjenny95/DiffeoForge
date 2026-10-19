# v139 — frozen media runtime repair

The frozen desktop could generate the native mean and PC endpoint meshes, then
fail when preparing their views because imageio looked up distribution metadata
that was absent from the bundle. Startup and direct FFmpeg recording checks did
not exercise this imageio import and plugin route.

The Windows spec explicitly collects imageio and imageio-ffmpeg metadata. A new
frozen media build gate encodes and decodes four synthetic MP4 frames through the
same imageio/FFmpeg route as the PCA movies, checking frame count, dimensions and
content. It opens no scientific project and launches no native scientific job.

Visualization preparation checks this runtime before native Shooting and honors
a cancellation during that check. Existing verified endpoint results are reused
on retry. Failure text identifies visualization preparation and keeps the atlas
and PCA available, rather than implying that all PC shapes failed.

Source checks cover successful encoding/decoding and cleanup, missing metadata,
early failure/cancellation, the freeze contract and existing media/view handling.
Frozen build and installer verification are separate from installed checks. Do
not alter an open installation or rerun the atlas to repair media preparation.
Automatic result preparation after convergence remains a separate backlog item.
