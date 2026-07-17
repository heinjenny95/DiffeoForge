"""Dependency-light launcher for the optional PySide6 desktop application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from diffeoforge import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the desktop launcher parser without importing Qt."""

    parser = argparse.ArgumentParser(
        prog="diffeoforge-desktop",
        description="Launch the DiffeoForge graphical project setup.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop window or construct it once for packaging smoke tests."""

    args = build_parser().parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication

        from diffeoforge.desktop.widgets import DiffeoForgeWindow
    except ModuleNotFoundError as error:
        if error.name == "PySide6" or (error.name or "").startswith("PySide6."):
            print(
                "ERROR: DiffeoForge Desktop is optional; install diffeoforge[desktop].",
                file=sys.stderr,
            )
            return 2
        raise

    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(["diffeoforge-desktop"])
    application.setApplicationName("DiffeoForge Desktop")
    application.setOrganizationName("DiffeoForge")

    window = DiffeoForgeWindow()
    if args.smoke:
        window.show()
        application.processEvents()
        window.close()
        return 0

    window.show()
    return application.exec() if owns_application else 0


if __name__ == "__main__":
    raise SystemExit(main())
