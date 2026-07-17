from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_harness import main, run_reference_worker_harness
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerEvent,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _request(tmp_path: Path) -> DesktopReferenceLaunchRequest:
    config = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    return DesktopReferenceLaunchRequest(
        request_id="reference-harness-test",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=sha256_file(config),
        launcher_engine="docker",
        launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )


def _run(request: DesktopReferenceLaunchRequest):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_reference_worker_harness(
        stdin=io.StringIO(json.dumps(request.as_dict()) + "\n"),
        stdout=stdout,
        stderr=stderr,
    )
    events = [
        DesktopReferenceWorkerEvent.from_dict(json.loads(line))
        for line in stdout.getvalue().splitlines()
    ]
    return code, events, stderr.getvalue()


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_reference_worker_harness_stops_before_prepare_without_mutation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    before = _files(tmp_path)

    code, events, stderr = _run(request)
    ledger = ReferenceWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)

    assert code == 0
    assert stderr == ""
    assert [event.kind for event in events] == ["accepted", "phase", "terminal"]
    assert events[1].payload["phase"] == "verify_request"
    assert ledger.reconcile().payload["outcome"] == "stopped_before_prepare"
    assert not request.destination.exists()
    assert _files(tmp_path) == before


def test_reference_worker_harness_reports_changed_bytes_without_mutation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    request.config_path.write_text(
        request.config_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    before = _files(tmp_path)

    code, events, stderr = _run(request)
    ledger = ReferenceWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)

    assert code == 1
    assert stderr == ""
    assert ledger.reconcile().payload["outcome"] == "failed"
    assert "changed after" in ledger.terminal.payload["message"]
    assert not request.destination.exists()
    assert _files(tmp_path) == before


def test_reference_worker_harness_rejects_malformed_transport() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_reference_worker_harness(
        stdin=io.StringIO("not json\n"),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("REFERENCE_WORKER_PROTOCOL_ERROR:")


def test_reference_worker_harness_rejects_additional_input(tmp_path: Path) -> None:
    request = _request(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_reference_worker_harness(
        stdin=io.StringIO(json.dumps(request.as_dict()) + "\n{}\n"),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert "exactly one request" in stderr.getvalue()


def test_reference_worker_harness_rejects_arguments(capsys) -> None:
    assert main(["unexpected"]) == 2
    assert "command-line arguments are not supported" in capsys.readouterr().err


def test_reference_worker_harness_real_pipe_round_trip_without_mutation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    before = _files(tmp_path)
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_path, environment.get("PYTHONPATH", "")) if item
    )

    completed = subprocess.run(
        [sys.executable, "-m", "diffeoforge.desktop.reference_worker_harness"],
        input=json.dumps(request.as_dict(), sort_keys=True) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=ROOT,
        env=environment,
        timeout=30,
        check=False,
    )
    events = [
        DesktopReferenceWorkerEvent.from_dict(json.loads(line))
        for line in completed.stdout.splitlines()
    ]
    ledger = ReferenceWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert ledger.reconcile().payload["outcome"] == "stopped_before_prepare"
    assert not request.destination.exists()
    assert _files(tmp_path) == before
