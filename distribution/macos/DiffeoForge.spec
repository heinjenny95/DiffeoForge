"""Native macOS bundle of the v193 GUI and its supervised sibling workers."""
import os
from pathlib import Path

repository = Path(SPEC).resolve().parents[2]
os.environ["DIFFEOFORGE_BUILD_ENTRYPOINT_PLATFORM"] = "macos"
shared_spec = repository / "distribution/windows/DiffeoForge.spec"
exec(compile(shared_spec.read_text(encoding="utf-8"), str(shared_spec), "exec"))
application = BUNDLE(
    bundle,
    name="DiffeoForge.app",
    bundle_identifier="org.diffeoforge.desktop",
    version="193",
    info_plist={
        "CFBundleShortVersionString": "0.0.193",
        "CFBundleVersion": "193",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSMinimumSystemVersion": "15.0",
    },
)
