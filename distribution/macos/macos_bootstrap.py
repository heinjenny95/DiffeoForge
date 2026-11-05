"""Expose only the adjacent, explicitly packaged reference executable."""
import os
import sys
from pathlib import Path


def configure_runtime_path():
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return
    contents = Path(sys.executable).resolve().parents[1]
    native = contents / "Resources/ReferenceRuntime/bin"
    if (native / "deformetrica").is_file():
        os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")

