"""Prove hard-parent-death containment of the source preparation worker."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from diffeoforge.desktop.reference_preparation_request import (
    DesktopReferencePreparationRequest,
    build_reference_preparation_request,
)
from diffeoforge.desktop.reference_preparation_worker_controller import (
    ReferencePreparationWorkerController,
)
from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob

HARD_PARENT_EXIT_CODE = 73
UNEXPECTED_CONTROLLER_RETURN_CODE = 74
DEFAULT_TIMEOUT_SECONDS = 10.0
CREATE_SUSPENDED = 0x00000004
WORKER_MODULE = "diffeoforge.desktop.reference_preparation_worker_harness"
STATUS = "source_preparation_worker_terminated_after_hard_parent_death_before_request"
CHECKS = [
    "approval_bound_request_preverified",
    "destination_absent_before_audit",
    "private_stage_absent_before_audit",
    "real_preparation_worker_created_suspended",
    "windows_kill_on_close_job_assignment_completed",
    "controller_hard_exited_after_job_assignment",
    "worker_stopped_within_timeout",
    "request_never_delivered",
    "destination_absent_after_audit",
    "private_stage_absent_after_audit",
    "approval_and_config_unchanged",
    "engine_execution_not_started",
]
SCIENTIFIC_BOUNDARY = (
    "This Windows engineering audit proves that the real source preparation-worker "
    "process was created suspended, assigned to a kill-on-close Job, and terminated "
    "after immediate hard controller death before any request was delivered. It does "
    "not prove frozen-bundle containment, termination after preparation starts, crash "
    "recovery, engine execution or interruption, scientific validity, numerical "
    "equivalence, registration quality, convergence, or biological interpretation."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("approval", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--expect-request-sha256", required=True)
    parser.add_argument("--worker-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--controller-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pid-path", type=Path, help=argparse.SUPPRESS)
    return parser


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request(
    approval: Path,
    config: Path,
    expected_request_sha256: str,
) -> DesktopReferencePreparationRequest:
    return build_reference_preparation_request(
        approval,
        config,
        expected_approval_sha256=expected_request_sha256,
        request_id="source-preparation-parent-death-evidence",
    )


def _private_stages(request: DesktopReferencePreparationRequest) -> tuple[Path, ...]:
    pattern = f".diffeoforge-preparing-{request.run_id}-*"
    return tuple(sorted(request.destination.parent.glob(pattern)))


class _HardExitAfterAssignmentJob:
    """Hard-exit only after the real Windows Job assignment has completed."""

    def __init__(self, pid_path: Path) -> None:
        self._job = WindowsKillOnCloseJob()
        self._pid_path = pid_path

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        self._job.assign(process)
        with self._pid_path.open("x", encoding="ascii", newline="\n") as handle:
            handle.write(f"{process.pid}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os._exit(HARD_PARENT_EXIT_CODE)

    def close(self) -> None:
        self._job.close()


def _run_controller_child(
    approval: Path,
    config: Path,
    expected_request_sha256: str,
    worker_python: Path,
    pid_path: Path,
) -> int:
    import diffeoforge.desktop.reference_preparation_worker_controller as controller_module

    request = _request(approval, config, expected_request_sha256)
    if request.destination.exists():
        raise FileExistsError(
            "Preparation parent-death audit destination already exists: "
            f"{request.destination}"
        )
    if _private_stages(request):
        raise FileExistsError(
            "Preparation parent-death audit found a pre-existing private stage"
        )
    real_popen = subprocess.Popen

    def suspended_popen(*args, **kwargs):
        creationflags = int(kwargs.get("creationflags", 0))
        kwargs["creationflags"] = creationflags | CREATE_SUSPENDED
        return real_popen(*args, **kwargs)

    controller_module.subprocess.Popen = suspended_popen
    controller_module._create_windows_preparation_job = lambda: (
        _HardExitAfterAssignmentJob(pid_path)
    )
    controller = ReferencePreparationWorkerController(
        request,
        worker_command=(str(worker_python), "-m", WORKER_MODULE),
    )
    controller.run()
    return UNEXPECTED_CONTROLLER_RETURN_CODE


def _process_is_active(process_id: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _terminate_process(process_id: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    process_terminate = 0x0001
    handle = kernel32.OpenProcess(process_terminate, False, process_id)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)


def _wait_until_stopped(process_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_active(process_id):
            return True
        time.sleep(0.05)
    return not _process_is_active(process_id)


def _evidence_schema() -> Mapping[str, Any]:
    resource = files("diffeoforge.schema").joinpath(
        "reference-preparation-parent-death-evidence-v0.1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_evidence(evidence: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_evidence_schema()).iter_errors(evidence),
        key=lambda error: list(error.path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.path) or "document"
    raise ValueError(
        "Preparation parent-death evidence schema violation at "
        f"{location}: {first.message}"
    )


def _run_outer(
    approval: Path,
    config: Path,
    expected_request_sha256: str,
    worker_python: Path,
    timeout: float,
) -> int:
    if os.name != "nt":
        raise RuntimeError("Preparation parent-death audit requires Windows")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    if not worker_python.is_file() or worker_python.is_symlink():
        raise FileNotFoundError(
            "Preparation worker Python does not exist or is symbolic: "
            f"{worker_python}"
        )
    approval_bytes = approval.read_bytes()
    config_bytes = config.read_bytes()
    request = _request(approval, config, expected_request_sha256)
    if request.destination.exists():
        raise FileExistsError(
            "Preparation parent-death audit destination already exists: "
            f"{request.destination}"
        )
    if _private_stages(request):
        raise FileExistsError(
            "Preparation parent-death audit found a pre-existing private stage"
        )

    worker_pid: int | None = None
    with tempfile.TemporaryDirectory(
        prefix="diffeoforge-preparation-parent-death-"
    ) as temporary:
        pid_path = Path(temporary) / "worker.pid"
        command = (
            sys.executable,
            str(Path(__file__).resolve()),
            str(approval),
            str(config),
            "--expect-request-sha256",
            expected_request_sha256,
            "--worker-python",
            str(worker_python),
            "--timeout",
            str(timeout),
            "--controller-child",
            "--pid-path",
            str(pid_path),
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                "Preparation controller child did not reach hard exit before timeout"
            ) from error
        if completed.returncode != HARD_PARENT_EXIT_CODE:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                "Preparation controller child did not hard-exit after Job assignment: "
                f"exit_code={completed.returncode}, stderr={stderr!r}"
            )
        try:
            worker_pid_text = pid_path.read_text(encoding="ascii").strip()
            if not worker_pid_text.isdecimal():
                raise ValueError("Preparation worker PID is not decimal")
            worker_pid = int(worker_pid_text)
            if not _wait_until_stopped(worker_pid, timeout):
                raise RuntimeError(
                    "Preparation worker remained active after hard controller death"
                )
        finally:
            if worker_pid is not None and _process_is_active(worker_pid):
                _terminate_process(worker_pid)

    if request.destination.exists():
        raise RuntimeError(
            "Preparation parent-death audit unexpectedly created the destination"
        )
    private_stages = _private_stages(request)
    if private_stages:
        raise RuntimeError(
            "Preparation parent-death audit unexpectedly created a private stage"
        )
    if approval.read_bytes() != approval_bytes or config.read_bytes() != config_bytes:
        raise RuntimeError("Preparation parent-death audit changed approval or config bytes")

    evidence = {
        "schema_version": "0.1",
        "status": STATUS,
        "platform": "windows",
        "controller_exit_code": HARD_PARENT_EXIT_CODE,
        "job_assignment_completed": True,
        "worker_started_suspended": True,
        "worker_stopped": True,
        "request_delivered": False,
        "destination": str(request.destination),
        "destination_exists": False,
        "private_stage_count": 0,
        "approval_request_sha256": _sha256_bytes(approval_bytes),
        "approved_plan_fingerprint": request.approved_plan_fingerprint,
        "worker": {"python": str(worker_python), "module": WORKER_MODULE},
        "engine_execution_started": False,
        "checks": CHECKS,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }
    _validate_evidence(evidence)
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    approval = args.approval.expanduser().resolve()
    config = args.config.expanduser().resolve()
    worker_python = args.worker_python.expanduser().resolve()
    try:
        if args.controller_child:
            if os.name != "nt" or args.pid_path is None:
                raise ValueError("controller child requires Windows and --pid-path")
            return _run_controller_child(
                approval,
                config,
                args.expect_request_sha256,
                worker_python,
                args.pid_path.expanduser().resolve(),
            )
        return _run_outer(
            approval,
            config,
            args.expect_request_sha256,
            worker_python,
            args.timeout,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
