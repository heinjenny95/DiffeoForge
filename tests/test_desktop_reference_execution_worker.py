from __future__ import annotations

import io
import json
import queue
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import diffeoforge.desktop.reference_execution_worker as execution_worker
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import (
    DesktopReferenceWorkerCommand,
    DesktopReferenceWorkerEvent,
    ReferenceWorkerEventLedger,
)
from diffeoforge.desktop.worker_protocol import sha256_file

ROOT = Path(__file__).resolve().parents[1]


class _CommandStream:
    def __init__(self, request_line: str, *commands: str) -> None:
        self._request_line = request_line
        self._read = False
        self._commands: queue.Queue[str] = queue.Queue()
        for command in commands:
            self._commands.put(command)

    def readline(self) -> str:
        if self._read:
            return ""
        self._read = True
        return self._request_line

    def __iter__(self):
        while True:
            command = self._commands.get()
            yield command


def _request(tmp_path: Path) -> DesktopReferenceLaunchRequest:
    config = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    return DesktopReferenceLaunchRequest(
        request_id="reference-execution-test",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=sha256_file(config),
        launcher_engine="docker",
        launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )


def _run(
    request: DesktopReferenceLaunchRequest,
    *commands: str,
    stream: _CommandStream | None = None,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    stream = stream or _CommandStream(json.dumps(request.as_dict()) + "\n", *commands)
    code = execution_worker.run_reference_execution_worker(
        stdin=stream,
        stdout=stdout,
        stderr=stderr,
    )
    events = tuple(
        DesktopReferenceWorkerEvent.from_dict(json.loads(line))
        for line in stdout.getvalue().splitlines()
    )
    ledger = ReferenceWorkerEventLedger(request)
    for event in events:
        ledger.accept(event)
    assert ledger.reconcile() == events[-1]
    return code, events, stderr.getvalue()


def test_reference_execution_worker_runs_full_lifecycle_and_emits_eta_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(execution_worker, "collect_preflight", lambda _path: object())

    def prepare(_config, *, run_id):
        assert run_id == request.run_id
        request.destination.mkdir(parents=True)
        return request.destination

    def execute(
        run_directory,
        *,
        line_callback,
        activity_callback,
        cancel_requested,
    ):
        assert run_directory == request.destination
        assert cancel_requested() is False
        activity_callback(
            5.0,
            "Started estimator: GradientAscent",
            "output/reference_info.log",
        )
        for iteration in range(4):
            line_callback(f"---------------- Iteration: {iteration} ----------------\n")
            line_callback(
                f">> Log-likelihood = {-10 + iteration:.3E} "
                "[ attachment = -8.000E+00 ; regularity = -2.000E+00 ]\n"
            )
        (request.destination / "result.json").write_text(
            '{"status":"completed"}\n', encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(execution_worker, "prepare_run", prepare)
    monkeypatch.setattr(execution_worker, "execute_run", execute)
    monkeypatch.setattr(
        execution_worker,
        "collect_run_report",
        lambda _path: SimpleNamespace(checks=(), result={"status": "completed"}),
    )
    times = iter((100.0, 101.0, 110.0, 111.0, 115.0, 116.0, 121.0, 122.0, 128.0))
    monkeypatch.setattr(execution_worker.time, "monotonic", lambda: next(times))

    code, events, stderr = _run(request)

    assert code == 0
    assert stderr == ""
    assert tuple(event.kind for event in events) == (
        "accepted",
        "phase",
        "phase",
        "phase",
        "phase",
        "activity",
        "progress",
        "progress",
        "progress",
        "progress",
        "phase",
        "phase",
        "terminal",
    )
    progress = tuple(event for event in events if event.kind == "progress")
    assert progress[-1].payload["iteration"] == 3
    assert progress[-1].payload["estimate_status"] == "observed_rate_to_iteration_cap"
    assert progress[-1].payload["eta_to_iteration_cap_seconds"] == pytest.approx(97 * 6)
    assert events[-1].payload["outcome"] == "completed"
    assert events[-1].payload["result_sha256"] == sha256_file(
        request.destination / "result.json"
    )


def test_reference_execution_worker_cancels_before_preparation_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    command = json.dumps(DesktopReferenceWorkerCommand(request.request_id).as_dict()) + "\n"
    stream = _CommandStream(json.dumps(request.as_dict()) + "\n", command)
    original_verify = DesktopReferenceLaunchRequest.verify_launch_inputs
    original_command_from_dict = DesktopReferenceWorkerCommand.from_dict.__func__
    command_validated = threading.Event()

    def observe_validated_command(cls, value):
        parsed = original_command_from_dict(cls, value)
        command_validated.set()
        return parsed

    monkeypatch.setattr(
        DesktopReferenceWorkerCommand,
        "from_dict",
        classmethod(observe_validated_command),
    )

    def verify_after_command_thread(self: DesktopReferenceLaunchRequest) -> None:
        assert command_validated.wait(timeout=5)
        original_verify(self)

    monkeypatch.setattr(
        DesktopReferenceLaunchRequest,
        "verify_launch_inputs",
        verify_after_command_thread,
    )

    code, events, _stderr = _run(request, stream=stream)

    assert code == 130
    assert events[-1].payload["outcome"] == "stopped_before_prepare"
    assert not request.destination.exists()


def test_reference_execution_worker_reports_launch_validation_failure(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    request.config_path.write_text("changed\n", encoding="utf-8")

    code, events, _stderr = _run(request)

    assert code == 1
    assert events[-1].payload["outcome"] == "failed"
    assert "changed after" in events[-1].payload["message"]
    assert not request.destination.exists()
