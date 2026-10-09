"""Cancel one frozen execution worker before mutation through its real controller."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from diffeoforge.config import resolve_output_directory
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerError,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_readiness import parse_reference_config_bytes
from diffeoforge.desktop.worker_protocol import sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Engineering smoke for the frozen Deformetrica execution worker. "
            "Cancellation is queued before launch so the external engine cannot start."
        )
    )
    parser.add_argument("worker", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--run-id", default="frozen-reference-execution-smoke")
    parser.add_argument("--request-id", default="frozen-reference-execution-smoke")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = args.worker.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    if worker.is_symlink() or not worker.is_file():
        print(f"ERROR: Frozen reference execution worker is missing or symbolic: {worker}")
        return 2
    try:
        config = parse_reference_config_bytes(config_path.read_bytes())
        launcher = config["runtime"]["launcher"]
        if launcher["type"] != "container":
            raise ValueError("Frozen execution smoke requires a container launcher config")
        destination = (resolve_output_directory(config, config_path) / args.run_id).resolve()
        if destination.exists():
            raise FileExistsError(f"Frozen execution smoke destination exists: {destination}")
        request = DesktopReferenceLaunchRequest(
            request_id=args.request_id,
            config_path=config_path,
            destination=destination,
            run_id=args.run_id,
            expected_config_sha256=sha256_file(config_path),
            launcher_engine=str(launcher["engine"]),
            launcher_image=str(launcher["image"]),
        )
        controller = ReferenceExecutionController(
            request,
            worker_command=(str(worker),),
        )
        if not controller.request_cancel() or controller.request_cancel():
            raise RuntimeError("Reference execution cancellation did not queue exactly once")
        result = controller.run()
        if (
            result.outcome != "stopped_before_prepare"
            or destination.exists()
            or result.exit_code != 130
        ):
            raise RuntimeError(
                "Frozen reference execution smoke did not stop before preparation"
            )
    except (
        OSError,
        ReferenceExecutionControllerError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}")
        return 2
    print(
        json.dumps(
            {
                "destination": str(destination),
                "destination_exists": False,
                "engine_execution_started": False,
                "events": len(result.events),
                "exit_code": result.exit_code,
                "outcome": result.outcome,
                "request_id": result.request_id,
                "worker": str(worker),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
