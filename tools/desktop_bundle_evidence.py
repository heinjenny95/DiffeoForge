"""Create or verify exact-file evidence for a Windows desktop freeze."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.desktop.freeze_evidence import (
    DesktopFreezeEvidenceError,
    create_desktop_freeze_evidence,
    verify_desktop_freeze_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Create or verify a non-release exact inventory for a Windows one-dir freeze.")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create non-overwriting evidence.")
    create.add_argument("bundle", type=Path)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--created-at")
    verify = subparsers.add_parser("verify", help="Verify existing evidence.")
    verify.add_argument("bundle", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            path = create_desktop_freeze_evidence(
                args.bundle,
                source_commit=args.source_commit,
                created_at=args.created_at,
            )
            print(f"Created desktop freeze evidence: {path}")
        else:
            manifest = verify_desktop_freeze_evidence(args.bundle)
            summary = {
                "status": manifest["status"],
                "target": manifest["target"],
                "source_commit": manifest["source"]["commit_sha"],
                "file_count": manifest["bundle"]["file_count"],
                "total_bytes": manifest["bundle"]["total_bytes"],
                "inventory_sha256": manifest["bundle"]["inventory_sha256"],
            }
            print(json.dumps(summary, sort_keys=True))
    except (DesktopFreezeEvidenceError, FileExistsError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
