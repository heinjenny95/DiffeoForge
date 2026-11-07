"""PyInstaller entry point for the pipe-only DiffeoForge numerical worker."""

import sys

if sys.argv[1:2] == ["--mesh-filter-worker"]:
    from diffeoforge.mesh_filter_worker import main

    raise SystemExit(main(sys.argv[2:]))

from diffeoforge.desktop.worker import _process_main

if __name__ == "__main__":
    _process_main()
