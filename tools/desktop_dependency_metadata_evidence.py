"""Create or verify hash-bound dependency metadata evidence for a freeze."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.dependency_metadata_evidence import (
    DesktopDependencyMetadataEvidenceError,
    create_desktop_dependency_metadata_evidence,
    verify_desktop_dependency_metadata_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create or verify non-release installed distribution metadata evidence."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create non-overwriting evidence.")
    create.add_argument("bundle", type=Path)
    create.add_argument("--expect-freeze-evidence-sha256", required=True)
    create.add_argument("--output-directory", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="Verify downloaded evidence.")
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--expect-freeze-evidence-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_desktop_dependency_metadata_evidence(
                args.bundle,
                expected_freeze_evidence_sha256=(
                    args.expect_freeze_evidence_sha256
                ),
                output_directory=args.output_directory,
            )
            print(f"Created dependency metadata evidence: {path}")
        else:
            evidence = verify_desktop_dependency_metadata_evidence(
                args.evidence,
                expected_freeze_evidence_sha256=(
                    args.expect_freeze_evidence_sha256
                ),
            )
            print(
                json.dumps(
                    {
                        "status": evidence["status"],
                        "target": evidence["target"],
                        "source_commit": evidence["source"]["source_commit_sha"],
                        "package_count": evidence["package_count"],
                        "package_set_sha256": evidence["package_set_sha256"],
                    },
                    sort_keys=True,
                )
            )
    except (
        ConfigurationError,
        DesktopDependencyMetadataEvidenceError,
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
