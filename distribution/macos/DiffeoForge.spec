"""Native macOS bundle of the GUI and its supervised sibling workers."""
import os
from pathlib import Path

from diffeoforge import __version__

build_number = __version__.removeprefix("0.0.0.dev")
if not build_number.isascii() or not build_number.isdecimal():
    raise RuntimeError("Mac test bundles require a private alpha version")

repository = Path(SPEC).resolve().parents[2]
os.environ["DIFFEOFORGE_BUILD_ENTRYPOINT_PLATFORM"] = "macos"
shared_spec = repository / "distribution/windows/DiffeoForge.spec"
exec(compile(shared_spec.read_text(encoding="utf-8"), str(shared_spec), "exec"))
application = BUNDLE(
    bundle,
    name="DiffeoForge.app",
    icon=str(asset_directory / "app-icon.icns"),
    bundle_identifier="org.diffeoforge.desktop",
    version=build_number,
    info_plist={
        "CFBundleShortVersionString": f"0.0.{build_number}",
        "CFBundleVersion": build_number,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSMinimumSystemVersion": "15.0",
    },
)
