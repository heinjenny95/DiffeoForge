"""Preflight, create, or offline-verify exact ISSigTool signature evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.inno_signature_evidence import (
    InnoSignatureEvidenceError,
    create_inno_signature_evidence,
    verify_inno_signature_evidence,
    verify_inno_signature_prerequisites,
)


def _input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("installer", type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--signature-tool", required=True, type=Path)
    parser.add_argument("--project-file", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="Fail closed unless all prerequisites permit the exact verifier operation.",
    )
    _input_arguments(preflight)

    create = subparsers.add_parser(
        "create",
        help="Create evidence from the exact nine-file raw observation boundary.",
    )
    _input_arguments(create)

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
        if args.command == "verify":
            evidence = verify_inno_signature_evidence(
                args.evidence,
                expected_evidence_sha256=args.expect_evidence_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": evidence["status"],
                        "installer_sha256": evidence["installer"]["sha256"],
                        "signature_tool_sha256": evidence["signature_tool"]["sha256"],
                        "issigtool_exit_code": evidence["issigtool_execution"]["exit_code"],
                        "installer_execution_authorized": evidence[
                            "installer_execution_authorized"
                        ],
                        "execution_authorized": evidence["execution_authorized"],
                    },
                    sort_keys=True,
                )
            )
        else:
            arguments = {
                "signature_path": args.signature,
                "public_key_path": args.public_key,
                "signature_tool_path": args.signature_tool,
                "project_file": args.project_file,
                "output_directory": args.output_directory,
                "source_commit": args.source_commit,
            }
            if args.command == "preflight":
                result = verify_inno_signature_prerequisites(args.installer, **arguments)
                print(json.dumps(result, sort_keys=True))
            else:
                path = create_inno_signature_evidence(args.installer, **arguments)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                print(f"Created Inno signature evidence: {path}")
                print(f"Inno signature evidence SHA-256: {digest}")
    except (
        ConfigurationError,
        InnoSignatureEvidenceError,
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
