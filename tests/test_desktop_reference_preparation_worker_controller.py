from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.desktop.reference_preparation_worker_controller as controller_module
from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
    build_reference_preparation_request,
)
from diffeoforge.desktop.reference_preparation_worker_controller import (
    ReferencePreparationControllerError,
    ReferencePreparationExecutionError,
    ReferencePreparationProcessError,
    ReferencePreparationProtocolViolation,
    ReferencePreparationWorkerController,
    default_reference_preparation_worker_command,
)
from diffeoforge.desktop.reference_preparation_worker_protocol import (
    DesktopReferencePreparationWorkerEvent,
)
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
)
from diffeoforge.runs import verify_prepared_run

ROOT = Path(__file__).resolve().parents[1]
CHECKS = [
    "approval_request_strict_and_schema_valid",
    "approval_request_matches_external_sha256",
    "embedded_plan_matches_approval_fingerprint",
    "fresh_current_plan_exactly_matches_approved_plan",
    "private_stage_exactly_matches_approved_protected_bytes",
    "approval_request_unchanged_before_atomic_publication",
    "destination_published_atomically_without_replace",
    "prepared_manifest_and_protected_files_verified",
    "prepared_lifecycle_has_no_execution_event",
    "prepared_output_is_pristine",
]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Preparation Controller Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _request(
    tmp_path: Path,
    *,
    run_id: str = "preparation-controller-001",
) -> DesktopReferencePreparationRequest:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id=run_id)
    approval = create_reference_preparation_approval(
        config,
        run_id=run_id,
        approved_fingerprint=reference_preparation_plan_fingerprint(plan),
    )
    approval_path = write_reference_preparation_approval(
        approval,
        root / "review" / "approval.json",
    )
    return build_reference_preparation_request(
        approval_path,
        config,
        expected_approval_sha256=hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        request_id=f"request-{run_id}",
    )


def _evidence(request: DesktopReferencePreparationRequest) -> dict:
    return {
        "schema_version": "0.1",
        "status": "prepared_approved_reference_run_not_executed",
        "preparer": {"diffeoforge": "test"},
        "approval_request": {
            "path": str(request.approval_path),
            "bytes": 2,
            "sha256": request.expected_approval_sha256,
            "expected_sha256": request.expected_approval_sha256,
        },
        "approved_plan": {
            "canonical_fingerprint": request.approved_plan_fingerprint,
            "run_id": request.run_id,
            "destination": str(request.destination),
            "subjects": 2,
            "protected_files": 8,
            "total_protected_bytes": 1,
        },
        "prepared_run": {
            "path": str(request.destination),
            "manifest_path": str(request.destination / "manifest.json"),
            "manifest_bytes": 2,
            "manifest_sha256": "d" * 64,
            "protected_files": 8,
            "lifecycle_last_event": "prepared",
            "output_empty": True,
            "engine_execution_started": False,
        },
        "checks": CHECKS,
        "scientific_boundary": "Preparation-only synthetic controller evidence.",
    }


def _accepted(
    request: DesktopReferencePreparationRequest,
    *,
    sequence: int = 0,
    request_id: str | None = None,
    config_sha256: str | None = None,
) -> DesktopReferencePreparationWorkerEvent:
    return DesktopReferencePreparationWorkerEvent(
        request_id=request.request_id if request_id is None else request_id,
        sequence=sequence,
        kind="accepted",
        payload={
            "operation": "prepare_approved_only",
            "approval_request_sha256": request.expected_approval_sha256,
            "config_sha256": (
                request.expected_config_sha256
                if config_sha256 is None
                else config_sha256
            ),
            "approved_plan_fingerprint": request.approved_plan_fingerprint,
            "run_id": request.run_id,
            "destination": str(request.destination),
            "engine_execution_authorized": False,
        },
    )


def _phase(
    request: DesktopReferencePreparationRequest,
    sequence: int,
    phase: str,
) -> DesktopReferencePreparationWorkerEvent:
    return DesktopReferencePreparationWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="phase",
        payload={"phase": phase, "message": phase},
    )


def _success(
    request: DesktopReferencePreparationRequest,
    *,
    sequence: int = 4,
    evidence: dict | None = None,
) -> DesktopReferencePreparationWorkerEvent:
    nested = _evidence(request) if evidence is None else evidence
    return DesktopReferencePreparationWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="terminal",
        payload={
            "outcome": "prepared_not_executed",
            "destination": str(request.destination),
            "destination_exists": True,
            "approval_request_sha256": request.expected_approval_sha256,
            "approved_plan_fingerprint": request.approved_plan_fingerprint,
            "manifest_sha256": nested["prepared_run"]["manifest_sha256"],
            "preparation_evidence": nested,
            "engine_execution_started": False,
            "message": "prepared only",
        },
    )


def _failed(
    request: DesktopReferencePreparationRequest,
    *,
    sequence: int = 2,
    destination_exists: bool = False,
) -> DesktopReferencePreparationWorkerEvent:
    return DesktopReferencePreparationWorkerEvent(
        request_id=request.request_id,
        sequence=sequence,
        kind="terminal",
        payload={
            "outcome": "failed",
            "destination": str(request.destination),
            "destination_exists": destination_exists,
            "approval_request_sha256": request.expected_approval_sha256,
            "approved_plan_fingerprint": request.approved_plan_fingerprint,
            "manifest_sha256": None,
            "preparation_evidence": None,
            "engine_execution_started": False,
            "message": "synthetic preparation failure",
        },
    )


def _success_lines(request: DesktopReferencePreparationRequest) -> list[str]:
    return [
        _accepted(request).to_json_line(),
        _phase(request, 1, "verify_request").to_json_line(),
        _phase(request, 2, "prepare_approved").to_json_line(),
        _phase(request, 3, "verify_prepared_run").to_json_line(),
        _success(request).to_json_line(),
    ]


def _failure_lines(request: DesktopReferencePreparationRequest) -> list[str]:
    return [
        _accepted(request).to_json_line(),
        _phase(request, 1, "verify_request").to_json_line(),
        _failed(request).to_json_line(),
    ]


def _fake_command(
    lines: list[str],
    *,
    exit_code: int,
    stderr_characters: int = 0,
    terminate_lines: bool = True,
    prefix_statements: tuple[str, ...] = (),
) -> tuple[str, ...]:
    statements = ["import sys", "sys.stdin.buffer.read()"]
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
    request: DesktopReferencePreparationRequest,
    lines: list[str],
    *,
    exit_code: int,
    stderr_characters: int = 0,
    stderr_limit: int = 65_536,
    stdout_line_limit: int = 262_144,
    terminate_lines: bool = True,
    prefix_statements: tuple[str, ...] = (),
) -> ReferencePreparationWorkerController:
    return ReferencePreparationWorkerController(
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


def test_default_command_is_source_only_and_refuses_unfrozen_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(controller_module.sys, "frozen", raising=False)
    assert default_reference_preparation_worker_command() == (
        sys.executable,
        "-m",
        "diffeoforge.desktop.reference_preparation_worker_harness",
    )

    monkeypatch.setattr(controller_module.sys, "frozen", True, raising=False)
    with pytest.raises(ReferencePreparationControllerError, match="not included"):
        default_reference_preparation_worker_command()


def test_controller_imports_no_gui_or_numerical_runtime() -> None:
    code = (
        "import sys; "
        "import diffeoforge.desktop.reference_preparation_worker_controller; "
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


def test_controller_rejects_invalid_constructor_arguments(tmp_path: Path) -> None:
    request = _request(tmp_path)
    with pytest.raises(ValueError, match="worker_command"):
        ReferencePreparationWorkerController(request, worker_command=())
    for invalid_timeout in (0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="supervision_timeout"):
            ReferencePreparationWorkerController(
                request,
                supervision_timeout=invalid_timeout,
            )
    with pytest.raises(ValueError, match="stdout_line_limit"):
        ReferencePreparationWorkerController(request, stdout_line_limit=True)
    with pytest.raises(ValueError, match="stderr_limit"):
        ReferencePreparationWorkerController(request, stderr_limit=0)


def test_controller_fails_closed_if_job_assignment_fails(
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
            raise OSError("synthetic preparation Job assignment failure")

        def close(self) -> None:
            self.closed = True

    job = FailingJob()
    monkeypatch.setattr(
        controller_module,
        "_create_windows_preparation_job",
        lambda: job,
    )
    controller = ReferencePreparationWorkerController(
        request,
        worker_command=(sys.executable, "-c", "import time;time.sleep(300)"),
    )

    with pytest.raises(ReferencePreparationProcessError, match="launch and contain"):
        controller.run()
    assert job.assigned_pid is not None
    assert job.closed is True
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_controller_rejects_partial_request_pipe_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)

    class PartialInput(io.BytesIO):
        def write(self, value: bytes) -> int:
            super().write(value[:-1])
            return len(value) - 1

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = PartialInput()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.pid = 12345
            self.returncode: int | None = None

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout=None):
            del timeout
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake = FakeProcess()
    monkeypatch.setattr(controller_module, "_create_windows_preparation_job", lambda: None)
    monkeypatch.setattr(controller_module.subprocess, "Popen", lambda *_a, **_k: fake)
    controller = ReferencePreparationWorkerController(
        request,
        worker_command=("synthetic-worker",),
    )

    with pytest.raises(ReferencePreparationProcessError, match="deliver"):
        controller.run()
    assert fake.returncode == -15
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_controller_rejects_stale_request_before_process_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    subject = request.config_path.parent / "synthetic" / "meshes" / "subject-01.vtk"
    subject.write_bytes(subject.read_bytes() + b"\n")

    def forbidden_launch(*_args, **_kwargs):
        raise AssertionError("a stale request must fail before process launch")

    monkeypatch.setattr(controller_module.subprocess, "Popen", forbidden_launch)
    controller = ReferencePreparationWorkerController(request, cwd=ROOT)

    with pytest.raises(ReferencePreparationControllerError, match="no longer valid"):
        controller.run()
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_real_controller_prepares_and_independently_verifies_without_execution(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    controller = ReferencePreparationWorkerController(request, cwd=ROOT)
    observed: list[DesktopReferencePreparationWorkerEvent] = []

    result = controller.run(event_callback=observed.append)

    assert result.prepared_not_executed is True
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.events == tuple(observed)
    assert [event.kind for event in result.events] == [
        "accepted",
        "phase",
        "phase",
        "phase",
        "terminal",
    ]
    assert result.manifest_sha256 == result.terminal_event.payload["manifest_sha256"]
    assert controller.state == "verified"
    verify_prepared_run(request.destination)
    assert list((request.destination / "output").iterdir()) == []
    assert not (request.destination / "result.json").exists()
    assert not (request.destination / "logs" / "deformetrica.log").exists()
    with pytest.raises(ReferencePreparationControllerError, match="single-use"):
        controller.run()


def test_schema_valid_failed_terminal_is_preserved(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = _fake_controller(request, _failure_lines(request), exit_code=1)

    with pytest.raises(
        ReferencePreparationExecutionError,
        match="synthetic preparation failure",
    ) as raised:
        controller.run()
    assert raised.value.event.payload["outcome"] == "failed"
    assert raised.value.exit_code == 1
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_schema_valid_failure_preserves_an_existing_destination(tmp_path: Path) -> None:
    request = _request(tmp_path)
    lines = [
        _accepted(request).to_json_line(),
        _phase(request, 1, "verify_request").to_json_line(),
        _phase(request, 2, "prepare_approved").to_json_line(),
        _failed(request, sequence=3, destination_exists=True).to_json_line(),
    ]
    marker = request.destination / "preserved.txt"
    controller = _fake_controller(
        request,
        lines,
        exit_code=1,
        prefix_statements=(
            "from pathlib import Path",
            f"Path({str(request.destination)!r}).mkdir(parents=True)",
            f"Path({str(marker)!r}).write_text('preserved', encoding='utf-8')",
        ),
    )

    with pytest.raises(ReferencePreparationExecutionError):
        controller.run()
    assert marker.read_text(encoding="utf-8") == "preserved"
    assert controller.state == "failed"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong_request", ReferencePreparationProtocolViolation),
        ("wrong_hash", ReferencePreparationProtocolViolation),
        ("skipped_sequence", ReferencePreparationProtocolViolation),
        ("skipped_phase", ReferencePreparationProtocolViolation),
        ("missing_phase", ReferencePreparationProtocolViolation),
        ("nested_manifest", ReferencePreparationProtocolViolation),
        ("extra_event", ReferencePreparationProtocolViolation),
        ("wrong_exit", ReferencePreparationProtocolViolation),
        ("malformed_json", ReferencePreparationProtocolViolation),
        ("duplicate_keys", ReferencePreparationProtocolViolation),
        ("missing_terminal", ReferencePreparationProcessError),
    ],
)
def test_controller_rejects_adversarial_event_streams(
    tmp_path: Path,
    case: str,
    expected: type[ReferencePreparationControllerError],
) -> None:
    request = _request(tmp_path)
    lines = _success_lines(request)
    exit_code = 0
    if case == "wrong_request":
        lines[0] = _accepted(request, request_id="different-request").to_json_line()
    elif case == "wrong_hash":
        lines[0] = _accepted(request, config_sha256="0" * 64).to_json_line()
    elif case == "skipped_sequence":
        lines[1] = _phase(request, 2, "verify_request").to_json_line()
    elif case == "skipped_phase":
        lines[2] = _phase(request, 2, "verify_prepared_run").to_json_line()
    elif case == "missing_phase":
        lines = [lines[0], lines[1], lines[2], _success(request, sequence=3).to_json_line()]
    elif case == "nested_manifest":
        evidence = _evidence(request)
        evidence["prepared_run"]["manifest_sha256"] = "e" * 64
        terminal = _success(request, evidence=evidence).as_dict()
        terminal["payload"]["manifest_sha256"] = "d" * 64
        lines[4] = json.dumps(terminal, sort_keys=True)
    elif case == "extra_event":
        lines.append("{}")
    elif case == "wrong_exit":
        lines = _failure_lines(request)
        exit_code = 0
    elif case == "malformed_json":
        lines = ["not-json"]
        exit_code = 2
    elif case == "duplicate_keys":
        lines = ['{"kind":"a","kind":"b"}']
        exit_code = 2
    else:
        lines = lines[:4]

    controller = _fake_controller(request, lines, exit_code=exit_code)
    with pytest.raises(expected):
        controller.run()
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_controller_rejects_oversized_or_unterminated_stdout(tmp_path: Path) -> None:
    request = _request(tmp_path)
    oversized = _fake_controller(
        request,
        ["x" * 200],
        exit_code=2,
        stdout_line_limit=64,
    )
    with pytest.raises(ReferencePreparationProtocolViolation, match="exceeds"):
        oversized.run()

    request = _request(tmp_path / "unterminated")
    unterminated = _fake_controller(
        request,
        [_accepted(request).to_json_line()],
        exit_code=0,
        terminate_lines=False,
    )
    with pytest.raises(ReferencePreparationProtocolViolation, match="LF-terminated"):
        unterminated.run()


def test_controller_drains_and_bounds_stderr(tmp_path: Path) -> None:
    request = _request(tmp_path)
    controller = _fake_controller(
        request,
        _failure_lines(request),
        exit_code=1,
        stderr_characters=100_000,
        stderr_limit=128,
    )

    with pytest.raises(ReferencePreparationExecutionError) as raised:
        controller.run()
    assert raised.value.stderr.startswith("x" * 128)
    assert raised.value.stderr.endswith("[stderr truncated by DiffeoForge]")
    assert len(raised.value.stderr) < 200


def test_timeout_preserves_private_crash_stage_without_reconciliation(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    private_stage = request.destination.parent / (
        f".diffeoforge-preparing-{request.run_id}-syntheticcrash"
    )
    command = _fake_command(
        [],
        exit_code=0,
        prefix_statements=(
            "from pathlib import Path",
            f"Path({str(private_stage)!r}).mkdir(parents=True)",
            "import time",
            "time.sleep(300)",
        ),
    )
    controller = ReferencePreparationWorkerController(
        request,
        worker_command=command,
        cwd=ROOT,
        supervision_timeout=0.3,
    )

    with pytest.raises(ReferencePreparationProcessError, match="timeout"):
        controller.run()
    assert controller.state == "failed"
    assert private_stage.is_dir()
    assert not request.destination.exists()


def test_parent_manifest_hash_mismatch_fails_but_preserves_prepared_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    monkeypatch.setattr(controller_module, "_sha256_file", lambda _path: "0" * 64)
    controller = ReferencePreparationWorkerController(request, cwd=ROOT)

    with pytest.raises(ReferencePreparationProtocolViolation, match="manifest SHA-256"):
        controller.run()
    assert controller.state == "failed"
    assert request.destination.is_dir()
    verify_prepared_run(request.destination)


def test_parent_manifest_binding_mismatch_preserves_prepared_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    real_verify = controller_module.verify_prepared_run

    def changed_manifest(path: Path) -> dict:
        manifest = dict(real_verify(path))
        manifest["source_config"] = dict(manifest["source_config"])
        manifest["source_config"]["sha256"] = "0" * 64
        return manifest

    monkeypatch.setattr(controller_module, "verify_prepared_run", changed_manifest)
    controller = ReferencePreparationWorkerController(request, cwd=ROOT)

    with pytest.raises(
        ReferencePreparationProtocolViolation,
        match="configuration SHA-256",
    ):
        controller.run()
    assert controller.state == "failed"
    assert request.destination.is_dir()
    real_verify(request.destination)
