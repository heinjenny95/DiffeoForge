# Private-alpha build numbering

## v78 — synchronized landmark overlays and visible build identity

The next private Windows test build is **v78**, package version
`0.0.0.dev78`. The main window and landmark editor show `v78 (Private Alpha)`;
the installer name is `DiffeoForge-v78-Windows-CPU-x86_64-Setup.exe` and its
installation entry shows the same label. CLI/Qt metadata retain the PEP 440
package version. The frozen evidence records the exact source commit.

Landmark overlays now use the camera of the displayed mesh image, including
while a newer image is pending. Meshes, saved coordinates, scientific algorithms
and QC approval requirements are unchanged. See `LARGE_MESH_VIEWER.md`.

Source verification: 155 focused tests passed, with two environment-specific
skips (installed PySide6 and unavailable Windows symlink privilege). Coverage
includes painted-frame synchronization, proxy picking, original-surface transfer,
editor drafts, main-window behavior and installer/freeze/SBOM contracts. Ruff and
whitespace checks passed. Installed-binary verification is recorded separately;
these tests are not a completed anatomical or end-to-end scientific validation.

## Reconstructed numbering gap

On 2026-09-15, the local installation backups were inspected to recover the
sequence after the explicitly labelled v71. **v72–v77 below are retrospective
sequence labels**, not claims that those historical binaries displayed them.
All those installers still used the stale package placeholder `0.0.0.dev0`.
No archived manifest or executable was rewritten.

| Label | Runtime source | Installed change |
| --- | --- | --- |
| v71 (original label) | `705a110` | Shape-space roundoff compatibility |
| v72 (reconstructed) | `c4d37f6` | Native landmark-import update |
| v73 (reconstructed) | `53b2bae` | NAS project-staging update |
| v74 (reconstructed) | `e9a4a0e` | Post-atlas QC update |
| v75 (reconstructed) | `8670974` | UX, AFK pilot, proxies and validation progress |
| v76 (reconstructed) | `063143a` | Background-renderer lifetime repair |
| v77 (reconstructed) | `3f31712` | Reduced-view landmark placement |
| v78 | See frozen build evidence | Frame-synchronous markers and explicit numbering |

The sequence is bound by the source fields in the installation backups made
before the JSON, NAS, QC, UX, renderer and landmark-proxy updates, followed by
the installed landmark-proxy build. Private backup locations are not published.
This numbering does not imply scientific validation, a public release, or an
engine/protocol version change.

## Required for every subsequent packaged change

1. Advance the private build number without reusing a shipped number.
2. Update `pyproject.toml`, `diffeoforge.__version__`, the handoff contract and
   its packaging wrapper together. `tests/test_build_version.py` rejects drift.
3. Add the change and test scope here; retain source commit/hash in build evidence.
4. Verify the window title, installer label/name and installed bundle identity.
5. Update GitHub and the Google Docs Project log. Do not publish installer
   artifacts or private research data without separate authorization.

Updating the version is not automatic for every Git commit: documentation-only
commits and intermediate source work are not additional installed builds.
