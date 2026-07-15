"""Command-line entry point for the pre-alpha workflow scaffold."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from diffeoforge import __version__
from diffeoforge.config import ConfigurationError, load_config, validate_input_paths
from diffeoforge.mesh import inspect_inputs
from diffeoforge.runs import execute_run, prepare_run, run_status


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
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Create a new immutable run directory without starting computation.",
    )
    prepare_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    prepare_parser.add_argument("--run-id", help="Explicit unique run identifier.")
    prepare_parser.add_argument(
        "--output-directory",
        type=Path,
        help="Override the configured run root for this preparation.",
    )

    execute_parser = subparsers.add_parser(
        "execute",
        help="Verify and execute a prepared run exactly once.",
    )
    execute_parser.add_argument("run_directory", type=Path)

    run_parser = subparsers.add_parser(
        "run",
        help="Prepare a new run directory and execute it immediately.",
    )
    run_parser.add_argument("config", type=Path, help="Path to an atlas YAML file.")
    run_parser.add_argument("--run-id", help="Explicit unique run identifier.")
    run_parser.add_argument(
        "--output-directory",
        type=Path,
        help="Override the configured run root for this run.",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Read the latest append-only lifecycle state for a run.",
    )
    status_parser.add_argument("run_directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "validate":
        try:
            config = load_config(args.config)
            print(f"Configuration schema valid: {args.config.resolve()}")
            if not args.schema_only:
                summary = validate_input_paths(config, args.config)
                template, subjects = inspect_inputs(summary)
                print(f"Input directory: {summary.input_directory}")
                print(f"Template: {summary.template}")
                print(f"Subject meshes: {summary.subject_count}")
                print(f"Template geometry: {template.points} points, {template.cells} triangles")
                point_counts = [subject.points for subject in subjects]
                print(
                    "Subject geometry: "
                    f"{min(point_counts)}-{max(point_counts)} points; all triangular VTK PolyData"
                )
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "prepare":
        try:
            run_directory = prepare_run(
                args.config,
                run_id=args.run_id,
                output_directory=args.output_directory,
            )
            print(f"Prepared run: {run_directory}")
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        return 0

    if args.command == "execute":
        try:
            return_code = execute_run(args.run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        if return_code != 0:
            print(f"ERROR: Deformetrica returned {return_code}.", file=sys.stderr)
            return 3
        return 0

    if args.command == "run":
        try:
            run_directory = prepare_run(
                args.config,
                run_id=args.run_id,
                output_directory=args.output_directory,
            )
            print(f"Prepared run: {run_directory}")
            return_code = execute_run(run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        if return_code != 0:
            print(f"ERROR: Deformetrica returned {return_code}.", file=sys.stderr)
            return 3
        return 0

    if args.command == "status":
        try:
            status = run_status(args.run_directory)
        except ConfigurationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")
