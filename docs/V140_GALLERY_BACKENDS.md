# v140 — packaged gallery file backends

The v139 media check exercised imageio video encoding, but gallery preparation
also writes Matplotlib PDFs. PyInstaller's automatic backend scan found Agg/Qt
and omitted the dynamically selected PDF writer. The app consequently stopped
gallery preparation with a missing `matplotlib.backends.backend_pdf` module.

The Windows build explicitly collects QtAgg, Agg, PDF and SVG across all five
entry points. Media preflight writes and checks PNG, JPEG, PDF and SVG output
with a local Agg canvas, without changing the live GUI's canvas. It also retains
the MP4 encode/decode check. Missing file backends now fail this build gate and
the early preflight, before native work. Existing atlas, PCA and endpoints are
not changed by this repair.

## Verification in progress

All 33 focused regressions pass with normal process exit, including missing
PDF/SVG dependency injection, endpoint reuse and export integrity. A separate
synthetic gallery probe exercises the actual renderer and Qt visualization panel:
17 PNGs, 17 PDFs, three six-view MP4s with 128 frames each, ZIP validation, all
five viewing tabs and Qt video decoding. Its 12 synthetic inputs remain unchanged.
Only the native sample batch is substituted with deterministic corresponding
vertices; no scientific backend or private project is launched by the probe.
The probe bound to the exact v139 product PYZ and shared runtime reproduces the
missing PDF module. The media command now returns failure without opening an
unhandled-exception window when a runtime check fails.

Frozen-package, installer and installed verification are separate gates and
remain pending. This source test does not establish scientific validity or
cross-platform support. Existing standalone gallery exports are not imported
or reassigned to another run by this packaging change.
