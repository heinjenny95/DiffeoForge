"""Preflight, create, or verify portable Inno compiler-toolchain evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.desktop.inno_portable_toolchain_evidence import (
    InnoPortableToolchainEvidenceError,
    create_inno_portable_toolchain_evidence,
    verify_inno_portable_toolchain_evidence,
    verify_inno_portable_toolchain_prerequisites,
)


def _input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("installer", type=Path)
    parser.add_argument("--toolchain-evidence", required=True, type=Path)
    parser.add_argument("--expect-toolchain-evidence-sha256", required=True)
    parser.add_argument("--signature-evidence", required=True, type=Path)
    parser.add_argument("--expect-signature-evidence-sha256", required=True)
    parser.add_argument("--project-file", required=True, type=Path)
    parser.add_argument("--toolchain-directory", required=True, type=Path)
    parser.add_argument("--probe-output-directory", required=True, type=Path)
    parser.add_argument("--evidence-output-directory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="Fail closed before the authenticated installer may prepare the toolchain.",
    )
    _input_arguments(preflight)

    create = subparsers.add_parser(
        "create",
        help="Create evidence from the exact four-file raw observation boundary.",
    )
    _input_arguments(create)

    verify = subparsers.add_parser(
        "verify",
        help="Offline-reconstruct the retained toolchain and compiler-probe evidence.",
    )
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--expect-evidence-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            evidence = verify_inno_portable_toolchain_evidence(
                args.evidence,
                expected_evidence_sha256=args.expect_evidence_sha256,
            )
            print(
                json.dumps(
                    {
                        "status": evidence["status"],
                        "installer_sha256": evidence["installer"]["sha256"],
                        "installed_file_count": evidence["portable_install"][
                            "installed_file_count"
                        ],
                        "compiler_probe_exit_code": evidence["compiler_probe"]["exit_code"],
                        "diffeoforge_installer_built": evidence["compiler_execution"][
                            "diffeoforge_installer_built"
                        ],
                        "execution_authorized": evidence["execution_authorized"],
                    },
                    sort_keys=True,
                )
            )
        else:
            arguments = {
                "toolchain_evidence_path": args.toolchain_evidence,
                "expected_toolchain_evidence_sha256": (
                    args.expect_toolchain_evidence_sha256
                ),
                "signature_evidence_path": args.signature_evidence,
                "expected_signature_evidence_sha256": (
                    args.expect_signature_evidence_sha256
                ),
                "project_file": args.project_file,
                "toolchain_directory": args.toolchain_directory,
                "probe_output_directory": args.probe_output_directory,
                "evidence_output_directory": args.evidence_output_directory,
                "source_commit": args.source_commit,
            }
            if args.command == "preflight":
                result = verify_inno_portable_toolchain_prerequisites(
                    args.installer, **arguments
                )
                print(json.dumps(result, sort_keys=True))
            else:
                path = create_inno_portable_toolchain_evidence(args.installer, **arguments)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                print(f"Created portable Inno toolchain evidence: {path}")
                print(f"Portable Inno toolchain evidence SHA-256: {digest}")
    except (
        ConfigurationError,
        InnoPortableToolchainEvidenceError,
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
