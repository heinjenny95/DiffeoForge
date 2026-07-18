"""PyInstaller entry point for approval-bound reference preparation only."""

from diffeoforge.desktop.reference_preparation_worker_harness import (
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
