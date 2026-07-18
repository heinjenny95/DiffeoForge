"""CLI for isolated Windows installer lifecycle evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from diffeoforge.desktop.installer_installation_evidence import (
    EVIDENCE_NAME,
    InstallerInstallationEvidenceError,
    create_installed_file_inventory,
    create_installer_installation_evidence,
    verify_installer_installation_evidence,
    verify_installer_installation_prerequisites,
    verify_retained_installer_installation_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight", help="Reconstruct all retained inputs before setup execution"
    )
    preflight.add_argument("build_evidence", type=Path)
    preflight.add_argument("--expect-build-evidence-sha256", required=True)
    preflight.add_argument("--project-file", type=Path, required=True)
    preflight.add_argument("--source-commit", required=True)

    snapshot = subparsers.add_parser(
        "snapshot", help="Verify and retain the complete installed-file inventory"
    )
    snapshot.add_argument("install_root", type=Path)
    snapshot.add_argument("build_evidence", type=Path)
    snapshot.add_argument("--expect-build-evidence-sha256", required=True)
    snapshot.add_argument("--output", type=Path, required=True)

    create = subparsers.add_parser(
        "create", help="Create canonical evidence after install, smoke, and uninstall"
    )
    create.add_argument("evidence_directory", type=Path)
    create.add_argument("build_evidence", type=Path)
    create.add_argument("--expect-build-evidence-sha256", required=True)
    create.add_argument("--project-file", type=Path, required=True)
    create.add_argument("--source-commit", required=True)

    verify = subparsers.add_parser(
        "verify", help="Reconstruct complete lifecycle evidence while source inputs exist"
    )
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--expect-evidence-sha256", required=True)

    retained = subparsers.add_parser(
        "verify-retained",
        help="Verify portable eight-file artifact integrity without build reconstruction",
    )
    retained.add_argument("evidence", type=Path)
    retained.add_argument("--expect-evidence-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = verify_installer_installation_prerequisites(
                args.build_evidence,
                expected_build_evidence_sha256=args.expect_build_evidence_sha256,
                project_file=args.project_file,
                source_commit=args.source_commit,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "snapshot":
            result = create_installed_file_inventory(
                args.install_root,
                args.build_evidence,
                expected_build_evidence_sha256=args.expect_build_evidence_sha256,
                output_file=args.output,
            )
            print(
                "Verified installed inventory: "
                f"{result['file_count']} files, {result['total_bytes']} bytes"
            )
            return 0
        if args.command == "create":
            create_installer_installation_evidence(
                args.evidence_directory,
                args.build_evidence,
                expected_build_evidence_sha256=args.expect_build_evidence_sha256,
                project_file=args.project_file,
                source_commit=args.source_commit,
            )
            print(f"Created isolated installer lifecycle evidence: {EVIDENCE_NAME}")
            return 0
        if args.command == "verify-retained":
            result = verify_retained_installer_installation_evidence(
                args.evidence,
                expected_evidence_sha256=args.expect_evidence_sha256,
            )
            print(
                "Verified retained installer lifecycle artifact integrity: "
                f"{result['status']}"
            )
            return 0
        result = verify_installer_installation_evidence(
            args.evidence, expected_evidence_sha256=args.expect_evidence_sha256
        )
        print(
            "Verified isolated installer lifecycle evidence: "
            f"{result['status']}"
        )
        return 0
    except (InstallerInstallationEvidenceError, OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
