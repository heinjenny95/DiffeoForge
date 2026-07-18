"""Create or verify a deterministic CycloneDX 1.7 Windows freeze SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.dependency_metadata_evidence import (
    DesktopDependencyMetadataEvidenceError,
)
from diffeoforge.desktop.freeze_evidence import DesktopFreezeEvidenceError
from diffeoforge.desktop.sbom import (
    DesktopSbomError,
    create_desktop_cyclonedx_sbom,
    verify_desktop_cyclonedx_sbom,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a non-overwriting SBOM pair.")
    create.add_argument("bundle", type=Path)
    create.add_argument("dependency_evidence", type=Path)
    create.add_argument("--expect-freeze-evidence-sha256", required=True)
    create.add_argument("--expect-dependency-evidence-sha256", required=True)
    create.add_argument("--output-directory", required=True, type=Path)

    verify = subparsers.add_parser(
        "verify",
        help="Verify a downloaded SBOM against downloaded source evidence.",
    )
    verify.add_argument("sbom", type=Path)
    verify.add_argument("freeze_evidence", type=Path)
    verify.add_argument("dependency_evidence", type=Path)
    verify.add_argument("--expect-freeze-evidence-sha256", required=True)
    verify.add_argument("--expect-dependency-evidence-sha256", required=True)
    verify.add_argument("--expect-sbom-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_desktop_cyclonedx_sbom(
                args.bundle,
                args.dependency_evidence,
                expected_freeze_evidence_sha256=(
                    args.expect_freeze_evidence_sha256
                ),
                expected_dependency_evidence_sha256=(
                    args.expect_dependency_evidence_sha256
                ),
                output_directory=args.output_directory,
            )
            print(f"Created deterministic CycloneDX 1.7 SBOM: {path}")
        else:
            document = verify_desktop_cyclonedx_sbom(
                args.sbom,
                freeze_evidence_path=args.freeze_evidence,
                dependency_evidence_path=args.dependency_evidence,
                expected_freeze_evidence_sha256=(
                    args.expect_freeze_evidence_sha256
                ),
                expected_dependency_evidence_sha256=(
                    args.expect_dependency_evidence_sha256
                ),
                expected_sbom_sha256=args.expect_sbom_sha256,
            )
            payload = args.sbom.read_bytes()
            print(
                json.dumps(
                    {
                        "bom_format": document["bomFormat"],
                        "component_count": len(document["components"]),
                        "composition": document["compositions"][0]["aggregate"],
                        "sbom_sha256": hashlib.sha256(payload).hexdigest(),
                        "serial_number": document["serialNumber"],
                        "spec_version": document["specVersion"],
                    },
                    sort_keys=True,
                )
            )
    except (
        ConfigurationError,
        DesktopDependencyMetadataEvidenceError,
        DesktopFreezeEvidenceError,
        DesktopSbomError,
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
