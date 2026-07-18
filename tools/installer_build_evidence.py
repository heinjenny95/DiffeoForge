"""Preflight, create, or verify engineering Windows installer build evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.installer_build_evidence import (
    InstallerBuildEvidenceError,
    create_installer_build_evidence,
    verify_installer_build_evidence,
    verify_installer_build_prerequisites,
)


def _input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", type=Path)
    parser.add_argument("--expect-plan-sha256", required=True)
    parser.add_argument("--portable-evidence", required=True, type=Path)
    parser.add_argument("--expect-portable-evidence-sha256", required=True)
    parser.add_argument("--project-file", required=True, type=Path)
    parser.add_argument("--evidence-output-directory", required=True, type=Path)
    parser.add_argument("--observer-source-commit", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser(
        "preflight", help="Fail closed before one exact engineering compiler run."
    )
    _input_arguments(preflight)
    create = subparsers.add_parser(
        "create", help="Create evidence after the exact setup output exists."
    )
    _input_arguments(create)
    verify = subparsers.add_parser(
        "verify", help="Offline-reconstruct retained installer build evidence."
    )
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--expect-evidence-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            evidence = verify_installer_build_evidence(
                args.evidence,
                expected_evidence_sha256=args.expect_evidence_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": evidence["status"],
                        "setup_sha256": evidence["compiler_execution"]["setup"]["sha256"],
                        "setup_execution_authorized": evidence[
                            "setup_execution_authorized"
                        ],
                        "distribution_authorized": evidence["distribution_authorized"],
                        "release_authorized": evidence["release_authorized"],
                    },
                    sort_keys=True,
                )
            )
        else:
            arguments = {
                "expected_plan_sha256": args.expect_plan_sha256,
                "portable_evidence_path": args.portable_evidence,
                "expected_portable_evidence_sha256": (
                    args.expect_portable_evidence_sha256
                ),
                "project_file": args.project_file,
                "evidence_output_directory": args.evidence_output_directory,
                "observer_source_commit": args.observer_source_commit,
            }
            if args.command == "preflight":
                result = verify_installer_build_prerequisites(args.plan, **arguments)
                print(json.dumps(result, sort_keys=True))
            else:
                path = create_installer_build_evidence(args.plan, **arguments)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                print(f"Created engineering installer build evidence: {path}")
                print(f"Installer build evidence SHA-256: {digest}")
    except (
        ConfigurationError,
        InstallerBuildEvidenceError,
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
