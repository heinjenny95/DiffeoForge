"""Prove hard-parent-death containment of the frozen preparation worker."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from audit_reference_preparation_parent_death import main as run_shared_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", type=Path)
    parser.add_argument("approval", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--expect-request-sha256", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_shared_audit(
        (
            str(args.approval),
            str(args.config),
            "--expect-request-sha256",
            args.expect_request_sha256,
            "--worker-executable",
            str(args.worker),
            "--evidence-profile",
            "frozen",
            "--timeout",
            str(args.timeout),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
