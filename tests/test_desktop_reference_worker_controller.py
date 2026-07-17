from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.desktop.reference_worker_controller as reference_controller
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_controller import (
    ReferenceHarnessController,
    ReferenceHarnessControllerError,
    ReferenceHarnessExecutionError,
    ReferenceHarnessProcessError,
    ReferenceHarnessProtocolViolation,
    default_reference_harness_command,
)
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.desktop.worker_protocol import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _request(tmp_path: Path) -> DesktopReferenceLaunchRequest:
    config = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    return DesktopReferenceLaunchRequest(
        request_id="reference-controller-test",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=sha256_file(config),
        launcher_engine="docker",
        launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )


def _accepted(
    request: DesktopReferenceLaunchRequest,
    *,
    sequence: int = 0,
    request_id: str | None = None,
    config_sha256: str | None = None,
) -> DesktopReferenceWorkerEvent:
    return DesktopReferenceWorkerEvent(
        request_id=request.request_id if request_id is None else request_id,
        sequence=sequence,
        kind="accepted",
        payload={
            "engine": "deformetrica_reference",
            "config_sha256": (
                request.expected_config_sha256
                if config_sha256 is None
                else config_sha256
            ),
            "destination": str(request.destination),
            "cancellation": "phase_dependent",
        },
    )


def _phase(
    request: DesktopReferenceLaunchRequest,
    *,
    sequence: int = 1,
    phase: str = "verify_request",
) -> DesktopReferenceWorkerEvent:
    return DesktopReferenceWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="phase",
        payload={"phase": phase, "message": phase},
    )


def _terminal(
    request: DesktopReferenceLaunchRequest,
    *,
    sequence: int = 2,
    outcome: str = "stopped_before_prepare",
    destination_exists: bool = False,
    result_sha256: str | None = None,
) -> DesktopReferenceWorkerEvent:
    return DesktopReferenceWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="terminal",
        payload={
            "outcome": outcome,
            "destination": str(request.destination),
            "destination_exists": destination_exists,
            "result_sha256": result_sha256,
            "message": "synthetic terminal",
        },
    )


def _success_lines(request: DesktopReferenceLaunchRequest) -> list[str]:
    return [
        _accepted(request).to_json_line(),
        _phase(request).to_json_line(),
        _terminal(request).to_json_line(),
    ]


def _fake_command(
    lines: list[str],
    *,
    exit_code: int,
    stderr_characters: int = 0,
    terminate_lines: bool = True,
    prefix_statements: tuple[str, ...] = (),
) -> tuple[str, ...]:
    statements = ["import sys"]
    statements.extend(prefix_statements)
    for line in lines:
        if terminate_lines:
            statements.append(f"print({line!r}, flush=True)")
        else:
            statements.append(f"sys.stdout.write({line!r});sys.stdout.flush()")
    if stderr_characters:
        statements.append(f"sys.stderr.write('x' * {stderr_characters})")
        statements.append("sys.stderr.flush()")
    statements.append(f"sys.exit({exit_code})")
    return (sys.executable, "-c", ";".join(statements))


def _fake_controller(
    request: DesktopReferenceLaunchRequest,
    lines: list[str],
    *,
    exit_code: int,
    stderr_characters: int = 0,
    stderr_limit: int = 65_536,
    stdout_line_limit: int = 65_536,
    terminate_lines: bool = True,
    prefix_statements: tuple[str, ...] = (),
) -> ReferenceHarnessController:
    return ReferenceHarnessController(
        request,
        worker_command=_fake_command(
            lines,
            exit_code=exit_code,
            stderr_characters=stderr_characters,
            terminate_lines=terminate_lines,
            prefix_statements=prefix_statements,
        ),
        cwd=ROOT,
        stderr_limit=stderr_limit,
        stdout_line_limit=stdout_line_limit,
    )


def test_default_reference_harness_command_distinguishes_source_and_frozen_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delattr(reference_controller.sys, "frozen", raising=False)
    assert default_reference_harness_command() == (
        sys.executable,
        "-m",
        "diffeoforge.desktop.reference_worker_harness",
    )

    desktop = tmp_path / "DiffeoForge.exe"
    monkeypatch.setattr(reference_controller.sys, "frozen", True, raising=False)
    monkeypatch.setattr(reference_controller.sys, "executable", str(desktop))
    suffix = ".exe" if reference_controller.os.name == "nt" else ""
    assert default_reference_harness_command() == (
        str(tmp_path.resolve() / f"DiffeoForgeReferenceWorker{suffix}"),
    )


def test_reference_controller_imports_no_gui_or_numerical_runtime() -> None:
    code = (
        "import sys; import diffeoforge.desktop.reference_worker_controller; "
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


def test_reference_controller_rejects_invalid_constructor_arguments(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    with pytest.raises(ValueError, match="worker_command"):
        ReferenceHarnessController(request, worker_command=())
    with pytest.raises(ValueError, match="supervision_timeout"):
        ReferenceHarnessController(request, supervision_timeout=0)
    with pytest.raises(ValueError, match="stdout_line_limit"):
        ReferenceHarnessController(request, stdout_line_limit=True)
    with pytest.raises(ValueError, match="stderr_limit"):
        ReferenceHarnessController(request, stderr_limit=0)


def test_reference_controller_fails_closed_if_job_assignment_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)

    class FailingJob:
        def __init__(self) -> None:
            self.assigned_pid: int | None = None
            self.closed = False

        def assign(self, process: subprocess.Popen[bytes]) -> None:
            self.assigned_pid = process.pid
            raise OSError("synthetic assignment failure")

        def close(self) -> None:
            self.closed = True

    job = FailingJob()
    monkeypatch.setattr(reference_controller, "_create_windows_harness_job", lambda: job)
    controller = ReferenceHarnessController(
        request,
        worker_command=(sys.executable, "-c", "import time;time.sleep(300)"),
    )

    with pytest.raises(ReferenceHarnessProcessError, match="launch and contain"):
        controller.run()
    assert job.assigned_pid is not None
    assert job.closed is True
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_real_reference_controller_verifies_harness_without_mutation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    controller = ReferenceHarnessController(request, cwd=ROOT)
    observed: list[DesktopReferenceWorkerEvent] = []

    result = controller.run(event_callback=observed.append)

    assert result.stopped_before_prepare is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.events == tuple(observed)
    assert [event.kind for event in result.events] == ["accepted", "phase", "terminal"]
    assert controller.state == "verified"
    assert not request.destination.exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    with pytest.raises(ReferenceHarnessControllerError, match="single-use"):
        controller.run()


def test_schema_valid_harness_failure_is_preserved(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    failed = _terminal(request, sequence=0, outcome="failed")
    controller = _fake_controller(request, [failed.to_json_line()], exit_code=1)

    with pytest.raises(ReferenceHarnessExecutionError, match="synthetic terminal") as raised:
        controller.run()
    assert raised.value.event == failed
    assert raised.value.exit_code == 1
    assert controller.state == "failed"
    assert not request.destination.exists()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong_request", ReferenceHarnessProtocolViolation),
        ("wrong_hash", ReferenceHarnessProtocolViolation),
        ("skipped_sequence", ReferenceHarnessProtocolViolation),
        ("wrong_phase", ReferenceHarnessProtocolViolation),
        ("missing_phase", ReferenceHarnessProtocolViolation),
        ("extra_event", ReferenceHarnessProtocolViolation),
        ("wrong_exit", ReferenceHarnessProtocolViolation),
        ("malformed_json", ReferenceHarnessProtocolViolation),
        ("missing_terminal", ReferenceHarnessProcessError),
    ],
)
def test_reference_controller_rejects_adversarial_event_streams(
    tmp_path: Path,
    case: str,
    expected: type[ReferenceHarnessControllerError],
) -> None:
    request = _request(tmp_path)
    lines = _success_lines(request)
    exit_code = 0
    if case == "wrong_request":
        lines[0] = _accepted(request, request_id="other-request").to_json_line()
    elif case == "wrong_hash":
        lines[0] = _accepted(request, config_sha256="0" * 64).to_json_line()
    elif case == "skipped_sequence":
        lines[1] = _phase(request, sequence=2).to_json_line()
    elif case == "wrong_phase":
        lines[1] = _phase(request, phase="preflight").to_json_line()
    elif case == "missing_phase":
        lines = [lines[0], _terminal(request, sequence=1).to_json_line()]
    elif case == "extra_event":
        lines.insert(2, _phase(request, sequence=2, phase="preflight").to_json_line())
        lines[3] = _terminal(request, sequence=3).to_json_line()
    elif case == "wrong_exit":
        exit_code = 1
    elif case == "malformed_json":
        lines = ["not-json"]
        exit_code = 2
    else:
        lines = lines[:2]

    controller = _fake_controller(request, lines, exit_code=exit_code)
    with pytest.raises(expected):
        controller.run()
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_reference_controller_rejects_oversized_stdout_line(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = _fake_controller(
        request,
        ["x" * 200],
        exit_code=2,
        stdout_line_limit=64,
    )

    with pytest.raises(ReferenceHarnessProtocolViolation, match="exceeds"):
        controller.run()


def test_reference_controller_drains_and_bounds_stderr(tmp_path: Path) -> None:
    request = _request(tmp_path)
    failed = _terminal(request, sequence=0, outcome="failed")
    controller = _fake_controller(
        request,
        [failed.to_json_line()],
        exit_code=1,
        stderr_characters=100_000,
        stderr_limit=128,
    )

    with pytest.raises(ReferenceHarnessExecutionError) as raised:
        controller.run()
    assert raised.value.stderr.startswith("x" * 128)
    assert raised.value.stderr.endswith("[stderr truncated by DiffeoForge]")
    assert len(raised.value.stderr) < 200


def test_reference_controller_rejects_unterminated_stdout(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = _fake_controller(
        request,
        [_accepted(request).to_json_line()],
        exit_code=0,
        terminate_lines=False,
    )
    with pytest.raises(ReferenceHarnessProtocolViolation, match="LF-terminated"):
        controller.run()
    assert controller.state == "failed"


def test_reference_controller_enforces_supervision_timeout(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = ReferenceHarnessController(
        request,
        worker_command=(sys.executable, "-c", "import time;time.sleep(300)"),
        supervision_timeout=0.2,
    )
    with pytest.raises(ReferenceHarnessProcessError, match="timeout"):
        controller.run()
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_reference_controller_reverifies_request_after_child_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    calls = 0
    real_verify = DesktopReferenceLaunchRequest.verify_launch_inputs

    def verify_twice(self: DesktopReferenceLaunchRequest) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic post-child change")
        real_verify(self)

    monkeypatch.setattr(
        DesktopReferenceLaunchRequest,
        "verify_launch_inputs",
        verify_twice,
    )
    controller = _fake_controller(request, _success_lines(request), exit_code=0)
    with pytest.raises(ReferenceHarnessProtocolViolation, match="parent reverification"):
        controller.run()
    assert calls == 2
    assert controller.state == "failed"


def test_reference_controller_rejects_destination_created_by_child(tmp_path: Path) -> None:
    request = _request(tmp_path)
    statements = (
        "from pathlib import Path",
        f"Path({str(request.destination)!r}).mkdir(parents=True)",
    )
    controller = _fake_controller(
        request,
        _success_lines(request),
        exit_code=0,
        prefix_statements=statements,
    )
    with pytest.raises(ReferenceHarnessProtocolViolation, match="reverification"):
        controller.run()
    assert controller.state == "failed"
    assert request.destination.is_dir()
