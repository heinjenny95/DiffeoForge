"""Run the frozen nonnumerical reference worker through its parent controller."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import resolve_output_directory
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_readiness import parse_reference_config_bytes
from diffeoforge.desktop.reference_worker_controller import (
    ReferenceHarnessController,
    ReferenceHarnessControllerError,
)
from diffeoforge.desktop.worker_protocol import sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Engineering smoke for the frozen nonnumerical reference-worker harness."
        )
    )
    parser.add_argument("worker", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--run-id", default="frozen-reference-harness-evidence")
    parser.add_argument("--request-id", default="frozen-reference-worker-evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = args.worker.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    if worker.is_symlink() or not worker.is_file():
        print(f"ERROR: Frozen reference worker does not exist or is symbolic: {worker}")
        return 2
    try:
        config = parse_reference_config_bytes(config_path.read_bytes())
        launcher = config["runtime"]["launcher"]
        if launcher["type"] != "container":
            raise ValueError("Frozen reference harness smoke requires a container launcher")
        destination = (resolve_output_directory(config, config_path) / args.run_id).resolve()
        request = DesktopReferenceLaunchRequest(
            request_id=args.request_id,
            config_path=config_path,
            destination=destination,
            run_id=args.run_id,
            expected_config_sha256=sha256_file(config_path),
            launcher_engine=str(launcher["engine"]),
            launcher_image=str(launcher["image"]),
        )
        result = ReferenceHarnessController(
            request,
            worker_command=(str(worker),),
        ).run()
    except (
        ReferenceHarnessControllerError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}")
        return 2
    summary = {
        "destination": str(request.destination),
        "destination_exists": request.destination.exists(),
        "events": len(result.events),
        "exit_code": result.exit_code,
        "outcome": result.terminal_event.payload["outcome"],
        "request_id": result.request_id,
        "stderr": result.stderr,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.stopped_before_prepare and not request.destination.exists() else 2


if __name__ == "__main__":
    raise SystemExit(main())
