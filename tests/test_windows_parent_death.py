from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob
from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerEvent,
    DesktopWorkerRequest,
    sha256_file,
)

ROOT = Path(__file__).parents[1]


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object evidence")


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


def _terminate_process_id(process_id: int) -> None:
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


def _wait_until_stopped(process_id: int, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_active(process_id):
            return True
        time.sleep(0.05)
    return not _process_is_active(process_id)


def test_kill_on_close_job_terminates_assigned_process() -> None:
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job = WindowsKillOnCloseJob()
    try:
        job.assign(process)
        job.close()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    assert job.closed is True
    assert process.poll() is not None
    assert time.monotonic() - started < 10


def test_hard_parent_exit_terminates_controller_worker(tmp_path: Path) -> None:
    root = tmp_path / "Parent death Käfer"
    root.mkdir()
    config = root / "modern.yaml"
    config.write_text("test config\n", encoding="utf-8")
    pid_path = root / "worker.pid"
    error_path = root / "controller.error"
    request = DesktopWorkerRequest(
        request_id="hard-parent-exit",
        config_path=config.resolve(),
        destination=(root / "unpublished result").resolve(),
        expected_config_sha256=sha256_file(config),
    )
    started = DesktopWorkerEvent(
        request_id=request.request_id,
        sequence=0,
        kind="started",
        payload={
            "engine": request.engine,
            "config_sha256": request.expected_config_sha256,
            "destination": str(request.destination),
            "cancellation": "cooperative_safe_points",
        },
    )
    worker_code = ";".join(
        (
            "import os,pathlib,time",
            f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()), encoding='ascii')",
            (
                "print("
                f"{json.dumps(started.as_dict(), ensure_ascii=True, sort_keys=True)!r}, "
                "flush=True)"
            ),
            "time.sleep(300)",
        )
    )
    launcher_code = "\n".join(
        (
            "import os,sys,threading,time",
            "from pathlib import Path",
            "from diffeoforge.desktop.worker_controller import DesktopWorkerController",
            "from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest",
            f"request=DesktopWorkerRequest.from_dict({request.as_dict()!r})",
            (
                "controller=DesktopWorkerController(request, "
                f"worker_command=(sys.executable,'-c',{worker_code!r}), cwd={str(ROOT)!r})"
            ),
            "def supervise():",
            "    try:",
            "        controller.run()",
            "    except BaseException as error:",
            f"        Path({str(error_path)!r}).write_text(repr(error), encoding='utf-8')",
            "threading.Thread(target=supervise, daemon=True).start()",
            "deadline=time.monotonic()+10",
            (
                f"while (controller._process is None or not Path({str(pid_path)!r}).is_file()) "
                "and time.monotonic()<deadline: time.sleep(0.01)"
            ),
            (
                f"assert controller._process is not None and Path({str(pid_path)!r}).is_file()"
            ),
            "os._exit(73)",
        )
    )
    parent = subprocess.run(
        [sys.executable, "-c", launcher_code],
        cwd=ROOT,
        check=False,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
        capture_output=True,
        text=True,
    )

    diagnostic = error_path.read_text(encoding="utf-8") if error_path.is_file() else ""
    assert parent.returncode == 73, f"{parent.stderr}\n{diagnostic}"
    worker_pid = int(pid_path.read_text(encoding="ascii"))
    try:
        assert _wait_until_stopped(worker_pid)
    finally:
        if _process_is_active(worker_pid):
            _terminate_process_id(worker_pid)
    assert not request.destination.exists()
