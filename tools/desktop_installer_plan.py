"""Create or verify a deterministic non-executing Windows installer build plan."""

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
from diffeoforge.desktop.installer_plan import (
    DesktopInstallerPlanError,
    create_desktop_installer_build_plan,
    verify_desktop_installer_build_plan,
)
from diffeoforge.desktop.sbom import DesktopSbomError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a canonical non-overwriting plan pair.")
    create.add_argument("bundle", type=Path)
    create.add_argument("evidence_directory", type=Path)
    create.add_argument("--project-file", required=True, type=Path)
    create.add_argument("--output-directory", required=True, type=Path)
    create.add_argument("--expect-freeze-evidence-sha256", required=True)
    create.add_argument("--expect-dependency-evidence-sha256", required=True)
    create.add_argument("--expect-sbom-sha256", required=True)
    create.add_argument("--release-candidate", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify and reconstruct an existing plan pair.")
    verify.add_argument("plan", type=Path)
    verify.add_argument("--expect-plan-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_desktop_installer_build_plan(
                args.bundle,
                args.evidence_directory,
                project_file=args.project_file,
                output_directory=args.output_directory,
                expected_freeze_evidence_sha256=(args.expect_freeze_evidence_sha256),
                expected_dependency_evidence_sha256=(args.expect_dependency_evidence_sha256),
                expected_sbom_sha256=args.expect_sbom_sha256,
                release_candidate=args.release_candidate,
            )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"Created non-executing installer build plan: {path}")
            print(f"Installer build plan SHA-256: {digest}")
        else:
            plan = verify_desktop_installer_build_plan(
                args.plan,
                expected_plan_sha256=args.expect_plan_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": plan["status"],
                        "target": plan["target"],
                        "source_commit": plan["source"]["commit_sha"],
                        "application_version": plan["source"]["application_version"],
                        "setup_filename": plan["output"]["setup_filename"],
                        "execution_authorized": plan["compiler"]["execution_authorized"],
                    },
                    sort_keys=True,
                )
            )
    except (
        ConfigurationError,
        DesktopDependencyMetadataEvidenceError,
        DesktopFreezeEvidenceError,
        DesktopInstallerPlanError,
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
