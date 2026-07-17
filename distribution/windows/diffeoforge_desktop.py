"""PyInstaller entry point for the windowed DiffeoForge desktop process."""

from diffeoforge.desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
