"""Probe uncancelled frozen startup without permitting preparation or execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import yaml

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerEvent,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs


def probe(worker: Path, config_path: Path, *, mismatch: bool, timeout: float) -> dict:
    root = config_path.parent
    request = DesktopReferenceLaunchRequest(
        request_id=f"uncancelled-startup-{mismatch}", config_path=config_path.resolve(),
        destination=(root / ("wrong-output" if mismatch else "runs") / "probe").resolve(),
        run_id="probe", expected_config_sha256=sha256_file(config_path),
        launcher_engine="docker", launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )
    process = subprocess.Popen(
        [str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", **hidden_windows_process_kwargs(),
    )
    output, errors = [], []
    threads = [
        threading.Thread(target=lambda: output.extend(process.stdout), daemon=True),
        threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    try:
        process.stdin.write(json.dumps(request.as_dict()) + "\n")
        process.stdin.flush()
        # No queued cancellation, EOF or communicate(): the listener must remain
        # waiting while the other thread loads the native numerical extension.
        code = process.wait(timeout=timeout)
        for thread in threads:
            thread.join(timeout=5)
        if code != 1 or errors or any(thread.is_alive() for thread in threads):
            raise RuntimeError(f"Unexpected startup exit/transport: {code}, {errors}")
        ledger = ReferenceWorkerEventLedger(request)
        for line in output:
            ledger.accept(DesktopReferenceWorkerEvent.from_dict(json.loads(line)))
        phases = [e.payload["phase"] for e in ledger.events if e.kind == "phase"]
        expected = ["verify_request"] if mismatch else ["verify_request", "preflight"]
        if (
            ledger.terminal is None or ledger.terminal.payload["outcome"] != "failed"
            or ledger.terminal.payload["destination_exists"] or phases != expected
            or request.destination.exists() or (root / "runs").exists()
            or sha256_file(config_path) != request.expected_config_sha256
        ):
            raise RuntimeError("Uncancelled startup did not reach its expected safe terminal")
        return {
            "phases": phases, "exit_code": code, "destination_exists": False,
            "engine_execution_started": False, "events": len(ledger.events),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    finally:
        if process.poll() is None:
            # Only this probe's child: its missing-input configuration cannot
            # prepare a run or start an external engine.
            process.kill()
            process.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    worker = args.worker.resolve()
    if not worker.is_file() or worker.is_symlink() or args.timeout <= 0:
        parser.error("A real worker executable and positive timeout are required")
    with tempfile.TemporaryDirectory(prefix="diffeoforge-worker-startup-") as scratch:
        root = Path(scratch)
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        config["input"]["directory"] = str(root / "absent-meshes")
        config["input"]["template"] = str(root / "absent-template.vtk")
        config["output"]["directory"] = str(root / "runs")
        config_path = root / "atlas.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        results = [
            probe(worker, config_path, mismatch=m, timeout=args.timeout) for m in (True, False)
        ]
    print(json.dumps({"uncancelled_startup": results, "worker": str(worker)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
