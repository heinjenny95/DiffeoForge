"""PyInstaller entry point for the nonnumerical reference-worker harness."""

from diffeoforge.desktop.reference_worker_harness import main

if __name__ == "__main__":
    raise SystemExit(main())
