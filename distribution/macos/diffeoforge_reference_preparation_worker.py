"""PyInstaller entry point for approval-bound reference preparation only."""
from macos_bootstrap import configure_runtime_path

from diffeoforge.desktop.reference_preparation_worker_harness import (
    main,
)

configure_runtime_path()

if __name__ == "__main__":
    raise SystemExit(main())
