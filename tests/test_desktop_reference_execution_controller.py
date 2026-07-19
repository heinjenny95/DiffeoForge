from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import diffeoforge.desktop.reference_execution_controller as controller_module
from diffeoforge.config import load_config
from diffeoforge.desktop.reference_execution_controller import (
    ReferenceExecutionController,
    ReferenceExecutionControllerError,
    ReferenceExecutionProtocolViolation,
    ReferenceExecutionWorkerError,
    default_reference_execution_worker_command,
)
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_protocol import DesktopReferenceWorkerEvent
from diffeoforge.desktop.worker_protocol import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _request(tmp_path: Path) -> DesktopReferenceLaunchRequest:
    config = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    return DesktopReferenceLaunchRequest(
        request_id="reference-execution-controller-test",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=sha256_file(config),
        launcher_engine="docker",
        launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )


def _event(request, sequence, kind, payload) -> str:
    return DesktopReferenceWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind=kind,
        payload=payload,
    ).to_json_line()


def _accepted(request, sequence=0) -> str:
    return _event(
        request,
        sequence,
        "accepted",
        {
            "engine": "deformetrica_reference",
            "config_sha256": request.expected_config_sha256,
            "destination": str(request.destination),
            "cancellation": "phase_dependent",
        },
    )


def _phase(request, sequence, phase) -> str:
    return _event(request, sequence, "phase", {"phase": phase, "message": phase})


def _terminal(request, sequence, outcome, *, result_sha256=None) -> str:
    return _event(
        request,
        sequence,
        "terminal",
        {
            "outcome": outcome,
            "destination": str(request.destination),
            "destination_exists": outcome != "stopped_before_prepare",
            "result_sha256": result_sha256,
            "message": outcome,
        },
    )


def _command(lines: list[str], *, exit_code: int, prefix: tuple[str, ...] = ()) -> tuple[str, ...]:
    statements = ["import sys", *prefix]
    statements.extend(f"print({line!r}, flush=True)" for line in lines)
    statements.append(f"sys.exit({exit_code})")
    return (sys.executable, "-c", ";".join(statements))


def test_default_reference_execution_command_has_source_and_frozen_forms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delattr(controller_module.sys, "frozen", raising=False)
    assert default_reference_execution_worker_command() == (
        sys.executable,
        "-m",
        "diffeoforge.desktop.reference_execution_worker",
    )
    monkeypatch.setattr(controller_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        controller_module.sys,
        "executable",
        str(tmp_path / "DiffeoForge.exe"),
    )
    suffix = ".exe" if controller_module.os.name == "nt" else ""
    assert default_reference_execution_worker_command() == (
        str(tmp_path.resolve() / f"DiffeoForgeReferenceExecutionWorker{suffix}"),
    )


def test_reference_execution_controller_accepts_verified_completed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    result_bytes = b'{"status":"completed"}\n'
    result_hash = hashlib.sha256(result_bytes).hexdigest()
    maximum = int(load_config(request.config_path)["optimization"]["max_iterations"])
    lines = [
        _accepted(request),
        _phase(request, 1, "verify_request"),
        _phase(request, 2, "preflight"),
        _phase(request, 3, "prepare"),
        _phase(request, 4, "execute"),
        _event(
            request,
            5,
            "progress",
            {
                "iteration": 1,
                "maximum_iterations": maximum,
                "log_likelihood": -1.0,
                "attachment": -0.8,
                "regularity": -0.2,
                "elapsed_seconds": 12.0,
                "seconds_per_iteration": None,
                "eta_to_iteration_cap_seconds": None,
                "estimate_status": "warming_up",
            },
        ),
        _phase(request, 6, "finalize"),
        _phase(request, 7, "verify_result"),
        _terminal(request, 8, "completed", result_sha256=result_hash),
    ]
    prefix = (
        "from pathlib import Path",
        f"destination=Path({str(request.destination)!r})",
        "destination.mkdir(parents=True)",
        f"(destination/'result.json').write_bytes({result_bytes!r})",
    )
    monkeypatch.setattr(
        controller_module,
        "collect_run_report",
        lambda _path: SimpleNamespace(checks=(), result={"status": "completed"}),
    )
    controller = ReferenceExecutionController(
        request,
        worker_command=_command(lines, exit_code=0, prefix=prefix),
        cwd=ROOT,
    )
    observed = []

    result = controller.run(event_callback=observed.append)

    assert result.completed is True
    assert result.interrupted is False
    assert result.events == tuple(observed)
    assert controller.state == "completed"
    assert controller.request_cancel() is False


def test_reference_execution_controller_preserves_schema_valid_worker_failure(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    failure = _terminal(request, 0, "failed")
    controller = ReferenceExecutionController(
        request,
        worker_command=_command([failure], exit_code=1),
        cwd=ROOT,
    )

    with pytest.raises(ReferenceExecutionWorkerError, match="failed"):
        controller.run()
    assert controller.state == "failed"


def test_reference_execution_controller_rejects_progress_limit_mismatch(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    lines = [
        _accepted(request),
        _phase(request, 1, "verify_request"),
        _phase(request, 2, "preflight"),
        _phase(request, 3, "prepare"),
        _phase(request, 4, "execute"),
        _event(
            request,
            5,
            "progress",
            {
                "iteration": 1,
                "maximum_iterations": 999,
                "log_likelihood": -1.0,
                "attachment": -0.8,
                "regularity": -0.2,
                "elapsed_seconds": 1.0,
                "seconds_per_iteration": None,
                "eta_to_iteration_cap_seconds": None,
                "estimate_status": "warming_up",
            },
        ),
    ]
    controller = ReferenceExecutionController(
        request,
        worker_command=_command(lines, exit_code=0),
        cwd=ROOT,
    )

    with pytest.raises(ReferenceExecutionProtocolViolation, match="iteration limit"):
        controller.run()
    assert controller.state == "failed"


def test_reference_execution_cancel_queued_during_process_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    accepted = _accepted(request)
    stopped = _terminal(request, 1, "stopped_before_prepare")
    script = ";".join(
        (
            "import sys",
            "request_line=sys.stdin.readline()",
            "cancel_line=sys.stdin.readline()",
            f"print({accepted!r}, flush=True)",
            f"print({stopped!r}, flush=True)",
            "sys.exit(130 if request_line and cancel_line else 2)",
        )
    )
    controller = ReferenceExecutionController(
        request,
        worker_command=(sys.executable, "-c", script),
        cwd=ROOT,
    )
    real_popen = subprocess.Popen
    created = threading.Event()
    release = threading.Event()

    def delayed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        created.set()
        assert release.wait(timeout=5)
        return process

    monkeypatch.setattr(controller_module.subprocess, "Popen", delayed_popen)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(controller.run)
        assert created.wait(timeout=5)
        assert controller.request_cancel() is True
        assert controller.request_cancel() is False
        release.set()
        result = future.result(timeout=10)

    assert result.outcome == "stopped_before_prepare"
    assert controller.state == "stopped_before_prepare"
    assert not request.destination.exists()


def test_reference_execution_cancel_can_be_queued_before_run(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = ReferenceExecutionController(request, cwd=ROOT)

    assert controller.request_cancel() is True
    assert controller.request_cancel() is False
    result = controller.run()

    assert result.outcome == "stopped_before_prepare"
    assert result.exit_code == 130
    assert controller.state == "stopped_before_prepare"
    assert not request.destination.exists()


def test_reference_execution_controller_is_single_use(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = ReferenceExecutionController(
        request,
        worker_command=_command(
            [_accepted(request), _terminal(request, 1, "stopped_before_prepare")],
            exit_code=130,
        ),
        cwd=ROOT,
    )
    controller.run()
    with pytest.raises(ReferenceExecutionControllerError, match="single-use"):
        controller.run()
