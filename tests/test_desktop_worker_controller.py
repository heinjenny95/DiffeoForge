from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import diffeoforge.desktop.worker_controller as worker_controller
from diffeoforge.desktop.worker_controller import (
    DesktopWorkerController,
    DesktopWorkerControllerError,
    DesktopWorkerExecutionError,
    DesktopWorkerProcessError,
    DesktopWorkerProtocolViolation,
)
from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerEvent,
    DesktopWorkerRequest,
    build_worker_request,
    sha256_file,
)
from diffeoforge.modern_progress import ModernProgressEvent

ROOT = Path(__file__).parents[1]
MESH_DIRECTORY = ROOT / "examples" / "synthetic" / "meshes"


def _protocol_request(tmp_path: Path) -> DesktopWorkerRequest:
    config = tmp_path / "modern-atlas.yaml"
    config.write_text("test configuration\n", encoding="utf-8")
    return DesktopWorkerRequest(
        request_id="controller-test",
        config_path=config.resolve(),
        destination=(tmp_path / "worker-run").resolve(),
        expected_config_sha256=sha256_file(config),
    )


def _started(
    request: DesktopWorkerRequest,
    *,
    sequence: int = 0,
    config_sha256: str | None = None,
    destination: Path | None = None,
) -> DesktopWorkerEvent:
    return DesktopWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="started",
        payload={
            "engine": "modern_cpu",
            "config_sha256": (
                request.expected_config_sha256 if config_sha256 is None else config_sha256
            ),
            "destination": str(request.destination if destination is None else destination),
            "cancellation": "cooperative_safe_points",
        },
    )


def _failed(
    request: DesktopWorkerRequest,
    *,
    sequence: int = 0,
    request_id: str | None = None,
) -> DesktopWorkerEvent:
    return DesktopWorkerEvent(
        request_id=request.request_id if request_id is None else request_id,
        sequence=sequence,
        kind="failed",
        payload={
            "error_type": "RuntimeError",
            "message": "synthetic failure",
            "destination": str(request.destination),
            "destination_exists": False,
        },
    )


def _progress(request: DesktopWorkerRequest, *, sequence: int = 0) -> DesktopWorkerEvent:
    progress = ModernProgressEvent(
        sequence=0,
        phase="workflow",
        status="started",
        message="started",
        completed_stages=0,
    )
    return DesktopWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="progress",
        payload={"modern_progress": progress.as_dict()},
    )


def _cancelled(request: DesktopWorkerRequest, *, sequence: int = 1) -> DesktopWorkerEvent:
    return DesktopWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="cancelled",
        payload={
            "destination": str(request.destination),
            "published": False,
            "resumable": False,
            "message": "synthetic cancellation",
        },
    )


def _fake_command(
    lines: list[str],
    *,
    exit_code: int,
    stderr_characters: int = 0,
) -> tuple[str, ...]:
    statements = ["import sys"]
    statements.extend(f"print({line!r}, flush=True)" for line in lines)
    if stderr_characters:
        statements.append(f"sys.stderr.write('x' * {stderr_characters})")
        statements.append("sys.stderr.flush()")
    statements.append(f"sys.exit({exit_code})")
    return (sys.executable, "-c", ";".join(statements))


def _fake_controller(
    request: DesktopWorkerRequest,
    lines: list[str],
    *,
    exit_code: int,
    stderr_limit: int = 65_536,
    stderr_characters: int = 0,
) -> DesktopWorkerController:
    return DesktopWorkerController(
        request,
        worker_command=_fake_command(
            lines,
            exit_code=exit_code,
            stderr_characters=stderr_characters,
        ),
        cwd=ROOT,
        stderr_limit=stderr_limit,
    )


def _modern_request(tmp_path: Path, *, max_cycles: int = 1) -> DesktopWorkerRequest:
    pytest.importorskip("numpy")
    pytest.importorskip("torch")
    from diffeoforge.modern_workflow import initialize_modern_workflow

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
        request_id="real-controller-test",
        destination=tmp_path / "worker-run",
    )


def test_controller_import_does_not_import_qt_or_numerical_engine() -> None:
    code = (
        "import sys; import diffeoforge.desktop.worker_controller; "
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


def test_schema_valid_worker_failure_is_preserved_as_typed_execution_error(
    tmp_path: Path,
) -> None:
    request = _protocol_request(tmp_path)
    controller = _fake_controller(
        request,
        [_failed(request).to_json_line()],
        exit_code=1,
    )

    with pytest.raises(DesktopWorkerExecutionError, match="synthetic failure") as raised:
        controller.run()

    assert raised.value.event.kind == "failed"
    assert raised.value.exit_code == 1
    assert controller.state == "failed"
    assert controller.request_cancel() is False


@pytest.mark.parametrize(
    "case",
    [
        "wrong_request",
        "wrong_start_hash",
        "wrong_start_destination",
        "skipped_sequence",
        "progress_before_started",
        "duplicate_started",
        "data_after_terminal",
        "missing_terminal",
        "wrong_exit_code",
        "malformed_json",
    ],
)
def test_controller_fails_closed_on_adversarial_event_streams(
    tmp_path: Path,
    case: str,
) -> None:
    request = _protocol_request(tmp_path)
    if case == "wrong_request":
        lines = [_failed(request, request_id="different-request").to_json_line()]
        exit_code = 1
    elif case == "wrong_start_hash":
        lines = [_started(request, config_sha256="0" * 64).to_json_line()]
        exit_code = 0
    elif case == "wrong_start_destination":
        lines = [_started(request, destination=tmp_path / "other-run").to_json_line()]
        exit_code = 0
    elif case == "skipped_sequence":
        lines = [_failed(request, sequence=1).to_json_line()]
        exit_code = 1
    elif case == "progress_before_started":
        lines = [_progress(request).to_json_line()]
        exit_code = 0
    elif case == "duplicate_started":
        lines = [_started(request).to_json_line(), _started(request, sequence=1).to_json_line()]
        exit_code = 0
    elif case == "data_after_terminal":
        lines = [_failed(request).to_json_line(), _started(request, sequence=1).to_json_line()]
        exit_code = 1
    elif case == "missing_terminal":
        lines = [_started(request).to_json_line()]
        exit_code = 0
    elif case == "wrong_exit_code":
        lines = [_failed(request).to_json_line()]
        exit_code = 0
    else:
        lines = ["not-json"]
        exit_code = 2
    controller = _fake_controller(request, lines, exit_code=exit_code)

    expected = (
        DesktopWorkerProcessError if case == "missing_terminal" else DesktopWorkerProtocolViolation
    )
    with pytest.raises(expected):
        controller.run()

    assert controller.state == "failed"
    assert not request.destination.exists()


def test_controller_drains_and_bounds_worker_stderr(tmp_path: Path) -> None:
    request = _protocol_request(tmp_path)
    controller = _fake_controller(
        request,
        [_failed(request).to_json_line()],
        exit_code=1,
        stderr_limit=128,
        stderr_characters=100_000,
    )

    with pytest.raises(DesktopWorkerExecutionError) as raised:
        controller.run()

    assert raised.value.stderr.startswith("x" * 128)
    assert raised.value.stderr.endswith("[stderr truncated by DiffeoForge]")
    assert len(raised.value.stderr) < 200


def test_cancel_requested_during_launch_is_queued_after_the_request_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _protocol_request(tmp_path)
    started = _started(request).to_json_line()
    cancelled = _cancelled(request).to_json_line()
    script = ";".join(
        (
            "import sys",
            "request_line=sys.stdin.readline()",
            "command_line=sys.stdin.readline()",
            f"print({started!r}, flush=True)",
            f"print({cancelled!r}, flush=True)",
            "sys.exit(130 if request_line and command_line else 2)",
        )
    )
    controller = DesktopWorkerController(
        request,
        worker_command=(sys.executable, "-c", script),
        cwd=ROOT,
    )
    real_popen = subprocess.Popen
    process_created = threading.Event()
    release_popen = threading.Event()

    def delayed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        process_created.set()
        if not release_popen.wait(timeout=5):
            process.kill()
            raise AssertionError("test did not release Popen")
        return process

    monkeypatch.setattr(worker_controller.subprocess, "Popen", delayed_popen)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(controller.run)
        assert process_created.wait(timeout=5)
        assert controller.request_cancel() is True
        assert controller.request_cancel() is False
        release_popen.set()
        result = future.result(timeout=10)

    assert result.cancelled is True
    assert result.exit_code == 130
    assert controller.state == "cancelled"
    assert not request.destination.exists()


def test_real_controller_completes_and_independently_verifies_result(tmp_path: Path) -> None:
    request = _modern_request(tmp_path)
    controller = DesktopWorkerController(request, cwd=ROOT)
    observed = []

    result = controller.run(event_callback=observed.append)

    assert result.completed is True
    assert result.cancelled is False
    assert result.exit_code == 0
    assert result.events == tuple(observed)
    assert result.events[0].kind == "started"
    assert result.terminal_event.kind == "completed"
    assert controller.state == "completed"
    assert controller.request_cancel() is False
    assert request.destination.is_dir()

    altered_payload = result.terminal_event.as_dict()["payload"]
    altered_payload["manifest_sha256"] = "0" * 64
    altered = DesktopWorkerEvent(
        request_id=request.request_id,
        sequence=result.terminal_event.sequence,
        kind="completed",
        payload=altered_payload,
    )
    with pytest.raises(DesktopWorkerProtocolViolation, match="manifest hash"):
        controller._verify_completion(altered)

    with pytest.raises(DesktopWorkerControllerError, match="single-use"):
        controller.run()


def test_real_controller_cancels_once_and_accepts_only_unpublished_terminal_state(
    tmp_path: Path,
) -> None:
    request = _modern_request(tmp_path, max_cycles=10)
    controller = DesktopWorkerController(request, cwd=ROOT)
    cancellation_results = []

    def observe(event: DesktopWorkerEvent) -> None:
        if event.kind == "started":
            cancellation_results.append(controller.request_cancel())

    result = controller.run(event_callback=observe)

    assert cancellation_results == [True]
    assert result.cancelled is True
    assert result.completed is False
    assert result.exit_code == 130
    assert result.terminal_event.payload["published"] is False
    assert result.terminal_event.payload["resumable"] is False
    assert controller.state == "cancelled"
    assert controller.request_cancel() is False
    assert not request.destination.exists()
    assert not tuple(tmp_path.glob(".worker-run.tmp-*"))
