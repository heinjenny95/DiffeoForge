"""PyInstaller entry point for the windowed DiffeoForge desktop process."""
from macos_bootstrap import configure_runtime_path

from diffeoforge.desktop.app import main

configure_runtime_path()

if __name__ == "__main__":
    raise SystemExit(main())
