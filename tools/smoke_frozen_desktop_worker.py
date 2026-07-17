"""Run one reviewed config through the frozen worker and fail-closed parent."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.desktop.worker_controller import (
    DesktopWorkerController,
    DesktopWorkerControllerError,
)
from diffeoforge.desktop.worker_protocol import build_worker_request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Engineering smoke for a frozen worker using the production parent protocol."
        )
    )
    parser.add_argument("worker", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--request-id", default="frozen-worker-evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = args.worker.expanduser().resolve()
    if worker.is_symlink() or not worker.is_file():
        print(f"ERROR: Frozen worker does not exist or is symbolic: {worker}")
        return 2
    try:
        request = build_worker_request(
            args.config,
            request_id=args.request_id,
            destination=args.destination,
        )
        result = DesktopWorkerController(
            request,
            worker_command=(str(worker),),
        ).run()
    except (DesktopWorkerControllerError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2
    summary = {
        "completed": result.completed,
        "destination": str(request.destination),
        "events": len(result.events),
        "exit_code": result.exit_code,
        "request_id": result.request_id,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
