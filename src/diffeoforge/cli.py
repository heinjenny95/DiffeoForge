"""Command-line entry point for the pre-alpha workflow scaffold."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError, load_config, validate_input_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffeoforge",
        description="Reproducible diffeomorphic atlas workflows for 3D surface meshes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an atlas configuration before any computation starts.",
    )
    validate_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    validate_parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Validate parameter structure without requiring input files to exist.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "validate":
        try:
            config = load_config(args.config)
            print(f"Configuration schema valid: {args.config.resolve()}")
            if not args.schema_only:
                summary = validate_input_paths(config, args.config)
                print(f"Input directory: {summary.input_directory}")
                print(f"Template: {summary.template}")
                print(f"Subject meshes: {summary.subject_count}")
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")
