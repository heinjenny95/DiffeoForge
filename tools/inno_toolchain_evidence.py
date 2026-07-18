"""Create or offline-verify exact Inno Setup authenticity evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.inno_toolchain_evidence import (
    InnoToolchainEvidenceError,
    create_inno_toolchain_evidence,
    verify_inno_toolchain_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create",
        help="Create evidence from the exact three-file raw observation boundary.",
    )
    create.add_argument("asset", type=Path)
    create.add_argument("--project-file", required=True, type=Path)
    create.add_argument("--output-directory", required=True, type=Path)
    create.add_argument("--source-commit", required=True)

    verify = subparsers.add_parser(
        "verify",
        help="Offline-verify exact raw observations and every available binding.",
    )
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--expect-evidence-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_inno_toolchain_evidence(
                args.asset,
                project_file=args.project_file,
                output_directory=args.output_directory,
                source_commit=args.source_commit,
            )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"Created non-executing Inno toolchain evidence: {path}")
            print(f"Inno toolchain evidence SHA-256: {digest}")
        else:
            evidence = verify_inno_toolchain_evidence(
                args.evidence,
                expected_evidence_sha256=args.expect_evidence_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": evidence["status"],
                        "asset_sha256": evidence["asset"]["sha256"],
                        "release_tag": evidence["release_attestation"]["release_tag"],
                        "authenticode_status": evidence["authenticode"]["status"],
                        "verifier_version": evidence["verifier"]["version"],
                        "execution_authorized": evidence["execution_authorized"],
                    },
                    sort_keys=True,
                )
            )
    except (
        ConfigurationError,
        InnoToolchainEvidenceError,
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
