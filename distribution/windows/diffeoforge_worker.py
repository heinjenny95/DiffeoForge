"""PyInstaller entry point for the pipe-only DiffeoForge numerical worker."""

from diffeoforge.desktop.worker import _process_main

if __name__ == "__main__":
    _process_main()
