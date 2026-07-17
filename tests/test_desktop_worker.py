from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

import diffeoforge.desktop.worker_protocol as worker_protocol
from diffeoforge.desktop.worker import run_worker
from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerCommand,
    DesktopWorkerEvent,
    DesktopWorkerProtocolError,
    DesktopWorkerRequest,
    _schema,
    build_worker_request,
    sha256_file,
)
from diffeoforge.modern_progress import ModernProgressEvent

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from diffeoforge.modern_workflow import (  # noqa: E402
    ModernWorkflowCancelled,
    initialize_modern_workflow,
    verify_modern_workflow,
)

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _request(tmp_path: Path, *, max_cycles: int = 1) -> DesktopWorkerRequest:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "modern-atlas.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
        attachment_kernel_width=0.45,
        deformation_kernel_width=0.6,
        noise_variance=0.01,
        max_cycles=max_cycles,
        threads=1,
    )
    return build_worker_request(
        config,
        request_id="desktop-worker-test",
        destination=tmp_path / "worker-run",
    )


def _events(output: str) -> list[DesktopWorkerEvent]:
    return [
        DesktopWorkerEvent.from_dict(json.loads(line))
        for line in output.splitlines()
        if line.strip()
    ]


def test_worker_schemas_are_valid_and_progress_is_composed_strictly() -> None:
    for name in (
        "desktop-worker-request-v0.1.json",
        "desktop-worker-command-v0.1.json",
        "desktop-worker-event-v0.1.json",
    ):
        jsonschema.Draft202012Validator.check_schema(_schema(name))

    progress = ModernProgressEvent(
        sequence=0,
        phase="workflow",
        status="started",
        message="started",
        completed_stages=0,
    ).as_dict()
    event = DesktopWorkerEvent(
        request_id="request-1",
        sequence=1,
        kind="progress",
        payload={"modern_progress": progress},
    )
    assert event.as_dict()["payload"]["modern_progress"] == progress

    invalid = event.as_dict()
    invalid["payload"]["modern_progress"]["eta_seconds"] = 5
    with pytest.raises(DesktopWorkerProtocolError, match="nested Modern progress"):
        DesktopWorkerEvent.from_dict(invalid)
    assert "eta_seconds" not in event.payload["modern_progress"]
    with pytest.raises(TypeError):
        event.payload["modern_progress"]["eta_seconds"] = 5


def test_protocol_import_does_not_import_qt_or_numerical_engine() -> None:
    code = (
        "import sys; import diffeoforge.desktop.worker_protocol; "
        "assert 'PySide6' not in sys.modules; assert 'torch' not in sys.modules; "
        "assert 'numpy' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_worker_rejects_malformed_initial_request_without_an_event() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    return_code = run_worker(
        stdin=io.StringIO("not-json\n"),
        stdout=stdout,
        stderr=stderr,
    )

    assert return_code == 2
    assert stdout.getvalue() == ""
    assert "WORKER_PROTOCOL_ERROR" in stderr.getvalue()
    assert "not valid JSON" in stderr.getvalue()


def test_request_binds_reviewed_config_bytes_and_refuses_changes(tmp_path: Path) -> None:
    request = _request(tmp_path)

    assert request.expected_config_sha256 == sha256_file(request.config_path)
    assert DesktopWorkerRequest.from_dict(request.as_dict()) == request
    request.config_path.write_text(
        request.config_path.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(DesktopWorkerProtocolError, match="changed after"):
        request.verify_launch_inputs()


def test_request_creation_refuses_a_config_that_changes_during_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = initialize_modern_workflow(
        MESH_DIRECTORY,
        units="unitless",
        config_path=tmp_path / "modern-atlas.yaml",
        template=MESH_DIRECTORY / "template.vtk",
        subject_pattern="subject-*.vtk",
    )
    observed_hashes = iter(("0" * 64, "1" * 64))
    monkeypatch.setattr(worker_protocol, "sha256_file", lambda _path: next(observed_hashes))

    with pytest.raises(DesktopWorkerProtocolError, match="changed while"):
        worker_protocol.build_worker_request(config, request_id="changing-config")


def test_worker_refuses_an_existing_destination_before_started_event(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.destination.mkdir()
    stdout = io.StringIO()

    return_code = run_worker(
        stdin=io.StringIO(json.dumps(request.as_dict()) + "\n"),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    events = _events(stdout.getvalue())
    assert return_code == 1
    assert [event.kind for event in events] == ["failed"]
    assert events[0].sequence == 0
    assert events[0].payload["destination_exists"] is True
    assert "already exists" in events[0].payload["message"]


def test_worker_subprocess_transports_progress_and_verified_completion(tmp_path: Path) -> None:
    request = _request(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "diffeoforge.desktop.worker"],
        cwd=ROOT,
        input=json.dumps(request.as_dict()) + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    events = _events(completed.stdout)
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[0].kind == "started"
    assert events[-1].kind == "completed"
    progress = [event.payload["modern_progress"] for event in events if event.kind == "progress"]
    assert progress[0]["phase"] == "workflow"
    assert progress[-1]["phase"] == "verification"
    assert all("eta_seconds" not in event for event in progress)
    manifest = verify_modern_workflow(request.destination)
    assert events[-1].payload["subject_count"] == len(manifest["input"]["subjects"])
    assert events[-1].payload["manifest_sha256"] == sha256_file(
        request.destination / "workflow-manifest.json"
    )


def test_worker_subprocess_accepts_cancel_command_and_publishes_nothing(tmp_path: Path) -> None:
    request = _request(tmp_path, max_cycles=10)
    command = DesktopWorkerCommand(request_id=request.request_id)
    completed = subprocess.run(
        [sys.executable, "-m", "diffeoforge.desktop.worker"],
        cwd=ROOT,
        input=(json.dumps(request.as_dict()) + "\n" + json.dumps(command.as_dict()) + "\n"),
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )

    assert completed.returncode == 130, completed.stderr
    assert completed.stderr == ""
    events = _events(completed.stdout)
    assert events[0].kind == "started"
    assert events[-1].kind == "cancelled"
    assert events[-1].payload["published"] is False
    assert events[-1].payload["resumable"] is False
    assert not request.destination.exists()
    assert not tuple(tmp_path.glob(".worker-run.tmp-*"))


def test_worker_cancel_command_emits_terminal_nonresumable_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "modern-atlas.yaml"
    config.write_text("test config\n", encoding="utf-8")
    request = DesktopWorkerRequest(
        request_id="cancel-test",
        config_path=config.resolve(),
        destination=(tmp_path / "cancelled-run").resolve(),
        expected_config_sha256=sha256_file(config),
    )
    command = DesktopWorkerCommand(request_id=request.request_id)

    def wait_for_cancel(*_args, cancel_requested, **_kwargs):
        deadline = time.monotonic() + 5
        while not cancel_requested():
            if time.monotonic() > deadline:
                raise AssertionError("cancel command was not observed")
            time.sleep(0.001)
        raise ModernWorkflowCancelled("cancelled")

    monkeypatch.setattr(
        "diffeoforge.modern_workflow.run_modern_workflow",
        wait_for_cancel,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    return_code = run_worker(
        stdin=io.StringIO(
            json.dumps(request.as_dict()) + "\n" + json.dumps(command.as_dict()) + "\n"
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert return_code == 130
    assert stderr.getvalue() == ""
    events = _events(stdout.getvalue())
    assert [event.kind for event in events] == ["started", "cancelled"]
    assert events[-1].payload["published"] is False
    assert events[-1].payload["resumable"] is False
    assert not request.destination.exists()


def test_malformed_worker_command_cancels_work_and_reports_protocol_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "modern-atlas.yaml"
    config.write_text("test config\n", encoding="utf-8")
    request = DesktopWorkerRequest(
        request_id="command-error",
        config_path=config.resolve(),
        destination=(tmp_path / "failed-run").resolve(),
        expected_config_sha256=sha256_file(config),
    )

    def wait_for_cancel(*_args, cancel_requested, **_kwargs):
        while not cancel_requested():
            time.sleep(0.001)
        raise ModernWorkflowCancelled("cancelled")

    monkeypatch.setattr(
        "diffeoforge.modern_workflow.run_modern_workflow",
        wait_for_cancel,
    )
    stdout = io.StringIO()
    return_code = run_worker(
        stdin=io.StringIO(json.dumps(request.as_dict()) + "\nnot-json\n"),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    events = _events(stdout.getvalue())
    assert return_code == 1
    assert [event.kind for event in events] == ["started", "failed"]
    assert events[-1].payload["error_type"] == "DesktopWorkerProtocolError"
    assert "not valid JSON" in events[-1].payload["message"]
