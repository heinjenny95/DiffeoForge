from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerEvent,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import sha256_file
from diffeoforge.subprocess_policy import hidden_windows_process_kwargs

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mismatch", [True, False])
def test_uncancelled_real_worker_reaches_a_safe_terminal_with_open_stdin(
    tmp_path: Path, mismatch: bool,
) -> None:
    pytest.importorskip("numpy")
    config = yaml.safe_load((ROOT / "examples/minimal-atlas-container.yaml").read_text())
    # Both variants are incapable of launching any scientific engine. The first
    # exercises native loading in request verification; the second reaches real
    # preflight with deliberately absent inputs and a correctly bound output.
    config["input"]["directory"] = str(tmp_path / "absent-meshes")
    config["input"]["template"] = str(tmp_path / "absent-template.vtk")
    config["output"]["directory"] = str(tmp_path / "runs")
    config_path = tmp_path / "atlas.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    request = DesktopReferenceLaunchRequest(
        request_id="uncancelled-startup", config_path=config_path.resolve(),
        destination=(tmp_path / ("wrong-output" if mismatch else "runs") / "probe").resolve(),
        run_id="probe", expected_config_sha256=sha256_file(config_path),
        launcher_engine="docker", launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "diffeoforge.desktop.reference_execution_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", **hidden_windows_process_kwargs(),
    )
    lines = []
    thread = threading.Thread(target=lambda: lines.extend(process.stdout), daemon=True)
    thread.start()
    try:
        process.stdin.write(json.dumps(request.as_dict()) + "\n")
        process.stdin.flush()
        # Deliberately keep stdin OPEN and send no cancellation. communicate()
        # would close it and hide the command-reader/native-import interaction.
        assert process.wait(timeout=20) == 1
        thread.join(timeout=5)
        assert not thread.is_alive()
        ledger = ReferenceWorkerEventLedger(request)
        for line in lines:
            ledger.accept(DesktopReferenceWorkerEvent.from_dict(json.loads(line)))
        assert ledger.terminal.payload["outcome"] == "failed"
        assert ledger.terminal.payload["destination_exists"] is False
        phases = [e.payload["phase"] for e in ledger.events if e.kind == "phase"]
        assert phases == (["verify_request"] if mismatch else ["verify_request", "preflight"])
        message = ledger.terminal.payload["message"].lower()
        assert ("different launch destination" if mismatch else "exist") in message
        assert process.stderr.read() == ""
        assert sha256_file(config_path) == request.expected_config_sha256
        assert not request.destination.exists()
        assert not (tmp_path / "runs").exists()
    finally:
        if process.poll() is None:
            process.kill()  # Only the isolated, invalid-input test child.
            process.wait(timeout=10)
        thread.join(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
