"""Run one externally approved preparation through the frozen worker/controller."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequestError,
    build_reference_preparation_request,
)
from diffeoforge.desktop.reference_preparation_worker_controller import (
    ReferencePreparationControllerError,
    ReferencePreparationWorkerController,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Engineering smoke for the frozen approval-bound reference-preparation "
            "worker. The approval must already exist and be independently hash-bound."
        )
    )
    parser.add_argument("worker", type=Path)
    parser.add_argument("approval", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--expect-request-sha256", required=True)
    parser.add_argument(
        "--request-id", default="frozen-reference-preparation-evidence"
    )
    return parser


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = args.worker.expanduser().resolve()
    approval = args.approval.expanduser().resolve()
    config = args.config.expanduser().resolve()
    if worker.is_symlink() or not worker.is_file():
        print(
            f"ERROR: Frozen reference preparation worker does not exist or is symbolic: "
            f"{worker}"
        )
        return 2

    try:
        approval_bytes = approval.read_bytes()
        config_bytes = config.read_bytes()
        request = build_reference_preparation_request(
            approval,
            config,
            expected_approval_sha256=args.expect_request_sha256,
            request_id=args.request_id,
        )
        result = ReferencePreparationWorkerController(
            request,
            worker_command=(str(worker),),
        ).run()
        if approval.read_bytes() != approval_bytes or config.read_bytes() != config_bytes:
            raise RuntimeError("Frozen preparation smoke changed approval or config bytes")
        payload = result.terminal_event.payload
        if (
            not result.prepared_not_executed
            or len(result.events) != 5
            or payload["engine_execution_started"] is not False
            or not request.destination.is_dir()
        ):
            raise RuntimeError(
                "Frozen preparation smoke did not reconcile the exact preparation-only "
                "outcome"
            )
    except (
        DesktopReferencePreparationRequestError,
        ReferencePreparationControllerError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}")
        return 2

    summary = {
        "approval_request_sha256": _sha256_bytes(approval_bytes),
        "config_sha256": _sha256_bytes(config_bytes),
        "destination": str(request.destination),
        "destination_exists": request.destination.is_dir(),
        "engine_execution_started": False,
        "events": len(result.events),
        "exit_code": result.exit_code,
        "manifest_sha256": result.manifest_sha256,
        "outcome": result.terminal_event.payload["outcome"],
        "request_id": result.request_id,
        "stderr": result.stderr,
        "worker": str(worker),
    }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
