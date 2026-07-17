"""Prove that hard controller death cannot orphan a frozen reference worker."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path

from diffeoforge.config import resolve_output_directory
from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_readiness import parse_reference_config_bytes
from diffeoforge.desktop.reference_worker_controller import ReferenceHarnessController
from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob
from diffeoforge.desktop.worker_protocol import sha256_file

HARD_PARENT_EXIT_CODE = 73
UNEXPECTED_CONTROLLER_RETURN_CODE = 74
DEFAULT_TIMEOUT_SECONDS = 10.0
CREATE_SUSPENDED = 0x00000004


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Windows engineering audit for hard-parent-death containment of a "
            "frozen nonnumerical reference worker."
        )
    )
    parser.add_argument("worker", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--controller-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pid-path", type=Path, help=argparse.SUPPRESS)
    return parser


def _request(config_path: Path) -> DesktopReferenceLaunchRequest:
    config = parse_reference_config_bytes(config_path.read_bytes())
    launcher = config["runtime"]["launcher"]
    if launcher["type"] != "container":
        raise ValueError("Frozen reference parent-death audit requires a container launcher")
    run_id = "frozen-reference-parent-death-evidence"
    destination = (resolve_output_directory(config, config_path) / run_id).resolve()
    return DesktopReferenceLaunchRequest(
        request_id="frozen-reference-parent-death-evidence",
        config_path=config_path,
        destination=destination,
        run_id=run_id,
        expected_config_sha256=sha256_file(config_path),
        launcher_engine=str(launcher["engine"]),
        launcher_image=str(launcher["image"]),
    )


class _HardExitAfterAssignmentJob:
    """Exit the controller only after a real Job assignment is complete."""

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


def _run_controller_child(worker: Path, config: Path, pid_path: Path) -> int:
    import diffeoforge.desktop.reference_worker_controller as controller_module

    request = _request(config)
    if request.destination.exists():
        raise FileExistsError(
            f"Reference parent-death audit destination already exists: {request.destination}"
        )
    real_popen = subprocess.Popen

    def suspended_popen(*args, **kwargs):
        creationflags = int(kwargs.get("creationflags", 0))
        kwargs["creationflags"] = creationflags | CREATE_SUSPENDED
        return real_popen(*args, **kwargs)

    controller_module.subprocess.Popen = suspended_popen
    controller_module._create_windows_harness_job = lambda: _HardExitAfterAssignmentJob(
        pid_path
    )
    controller = ReferenceHarnessController(
        request,
        worker_command=(str(worker),),
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


def _run_outer(worker: Path, config: Path, timeout: float) -> int:
    if os.name != "nt":
        raise RuntimeError("Frozen reference parent-death audit requires Windows")
    if not worker.is_file() or worker.is_symlink():
        raise FileNotFoundError(
            f"Frozen reference worker does not exist or is symbolic: {worker}"
        )
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request = _request(config)
    if request.destination.exists():
        raise FileExistsError(
            f"Reference parent-death audit destination already exists: {request.destination}"
        )
    worker_pid: int | None = None
    with tempfile.TemporaryDirectory(prefix="diffeoforge-reference-parent-death-") as temp:
        pid_path = Path(temp) / "worker.pid"
        command = (
            sys.executable,
            str(Path(__file__).resolve()),
            str(worker),
            str(config),
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
            raise RuntimeError("Controller child did not reach hard exit before timeout") from error
        if completed.returncode != HARD_PARENT_EXIT_CODE:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                "Controller child did not hard-exit after Job assignment: "
                f"exit_code={completed.returncode}, stderr={stderr!r}"
            )
        try:
            worker_pid_text = pid_path.read_text(encoding="ascii").strip()
            if not worker_pid_text.isdecimal():
                raise ValueError("worker PID is not decimal")
            worker_pid = int(worker_pid_text)
            if not _wait_until_stopped(worker_pid, timeout):
                raise RuntimeError(
                    "Frozen reference worker remained active after hard controller death"
                )
        finally:
            if worker_pid is not None and _process_is_active(worker_pid):
                _terminate_process(worker_pid)
    if request.destination.exists():
        raise RuntimeError("Parent-death audit unexpectedly created the destination")
    print(
        json.dumps(
            {
                "controller_exit_code": HARD_PARENT_EXIT_CODE,
                "destination": str(request.destination),
                "destination_exists": False,
                "job_assignment_completed": True,
                "worker": str(worker),
                "worker_started_suspended": True,
                "worker_stopped": True,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = args.worker.expanduser().resolve()
    config = args.config.expanduser().resolve()
    try:
        if args.controller_child:
            if os.name != "nt" or args.pid_path is None:
                raise ValueError("controller child requires Windows and --pid-path")
            return _run_controller_child(
                worker,
                config,
                args.pid_path.expanduser().resolve(),
            )
        return _run_outer(worker, config, args.timeout)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
