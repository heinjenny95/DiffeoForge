"""Dependency-light launcher for the optional PySide6 desktop application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

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
    parser.add_argument("--smoke-media", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop window or construct it once for packaging smoke tests."""

    args = build_parser().parse_args(argv)
    if args.smoke_media:
        from diffeoforge.media_runtime import verify_media_runtime

        try:
            verify_media_runtime()
        except Exception as error:
            if sys.stderr is not None:
                print(f"Media smoke failed: {error}", file=sys.stderr)
            return 1
        return 0
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from diffeoforge.desktop.widgets import DiffeoForgeWindow as Window
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
    application.setApplicationVersion(__version__)
    application.setOrganizationName("DiffeoForge")
    icon = QIcon(str(Path(__file__).with_name("assets") / "app-icon.png"))
    if args.smoke and icon.isNull():
        if sys.stderr is not None:
            print("DiffeoForge application icon could not be loaded.", file=sys.stderr)
        return 1
    application.setWindowIcon(icon)

    window = Window(recording_allowed=not args.smoke)
    window.setWindowIcon(icon)
    if args.smoke:
        window.show()
        application.processEvents()
        window.close()
        return 0

    window.show()
    return application.exec() if owns_application else 0


if __name__ == "__main__":
    raise SystemExit(main())
