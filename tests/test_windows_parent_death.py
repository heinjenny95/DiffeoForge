from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from diffeoforge.desktop.reference_prelaunch import DesktopReferenceLaunchRequest
from diffeoforge.desktop.reference_worker_controller import (
    ReferenceHarnessController,
    ReferenceHarnessProcessError,
)
from diffeoforge.desktop.windows_job import WindowsKillOnCloseJob
from diffeoforge.desktop.worker_protocol import (
    DesktopWorkerEvent,
    DesktopWorkerRequest,
    sha256_file,
)
from diffeoforge.reference_preparation_approval import (
    create_reference_preparation_approval,
    write_reference_preparation_approval,
)
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
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


def test_reference_controller_timeout_terminates_descendant_tree(tmp_path: Path) -> None:
    config = (tmp_path / "atlas.yaml").resolve()
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    pid_path = tmp_path / "descendant.pid"
    request = DesktopReferenceLaunchRequest(
        request_id="reference-timeout-tree",
        config_path=config,
        destination=(tmp_path / "runs" / "pilot-001").resolve(),
        run_id="pilot-001",
        expected_config_sha256=sha256_file(config),
        launcher_engine="docker",
        launcher_image="diffeoforge-deformetrica:4.3.0-cpu",
    )
    descendant_code = "import time;time.sleep(300)"
    worker_code = ";".join(
        (
            "import pathlib,subprocess,sys,time",
            (
                "child=subprocess.Popen("
                f"[sys.executable,'-c',{descendant_code!r}], "
                "creationflags=subprocess.CREATE_NO_WINDOW)"
            ),
            (
                f"pathlib.Path({str(pid_path)!r}).write_text("
                "str(child.pid), encoding='ascii')"
            ),
            "time.sleep(300)",
        )
    )
    controller = ReferenceHarnessController(
        request,
        worker_command=(sys.executable, "-c", worker_code),
        supervision_timeout=3,
    )

    with pytest.raises(ReferenceHarnessProcessError, match="timeout"):
        controller.run()

    descendant_pid = int(pid_path.read_text(encoding="ascii"))
    try:
        assert _wait_until_stopped(descendant_pid)
    finally:
        if _process_is_active(descendant_pid):
            _terminate_process_id(descendant_pid)
    assert controller.state == "failed"
    assert not request.destination.exists()


def test_reference_parent_death_audit_terminates_suspended_worker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Reference parent death Käfer"
    root.mkdir()
    config = root / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/audit_frozen_reference_parent_death.py",
            sys.executable,
            str(config),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["controller_exit_code"] == 73
    assert summary["job_assignment_completed"] is True
    assert summary["worker_started_suspended"] is True
    assert summary["worker_stopped"] is True
    assert summary["destination_exists"] is False
    assert not (root / "runs" / "frozen-reference-parent-death-evidence").exists()


def test_reference_execution_parent_death_audit_terminates_suspended_worker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Reference execution parent death"
    root.mkdir()
    config = root / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/audit_frozen_reference_parent_death.py",
            sys.executable,
            str(config),
            "--execution",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["controller_exit_code"] == 73
    assert summary["job_assignment_completed"] is True
    assert summary["worker_started_suspended"] is True
    assert summary["worker_stopped"] is True
    assert summary["worker_role"] == "execution"
    assert summary["destination_exists"] is False
    assert not (root / "runs" / "frozen-reference-parent-death-evidence").exists()


def test_preparation_parent_death_audit_terminates_real_suspended_worker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Preparation parent death Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    config = root / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    run_id = "source-preparation-parent-death"
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
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()
    before_approval = approval_path.read_bytes()
    before_config = config.read_bytes()

    completed = subprocess.run(
        [
            sys.executable,
            "tools/audit_reference_preparation_parent_death.py",
            str(approval_path),
            str(config),
            "--expect-request-sha256",
            approval_hash,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["schema_version"] == "0.1"
    assert evidence["status"] == (
        "source_preparation_worker_terminated_after_hard_parent_death_before_request"
    )
    assert evidence["controller_exit_code"] == 73
    assert evidence["job_assignment_completed"] is True
    assert evidence["worker_started_suspended"] is True
    assert evidence["worker_stopped"] is True
    assert evidence["request_delivered"] is False
    assert evidence["destination_exists"] is False
    assert evidence["private_stage_count"] == 0
    assert evidence["approval_request_sha256"] == approval_hash
    assert evidence["approved_plan_fingerprint"] == (
        approval["approval"]["approved_plan_fingerprint"]
    )
    assert evidence["worker"]["module"] == (
        "diffeoforge.desktop.reference_preparation_worker_harness"
    )
    assert evidence["engine_execution_started"] is False
    destination = Path(plan["run"]["destination"])
    assert not destination.exists()
    assert not tuple(
        destination.parent.glob(f".diffeoforge-preparing-{run_id}-*")
    )
    assert approval_path.read_bytes() == before_approval
    assert config.read_bytes() == before_config


def test_frozen_preparation_parent_death_audit_terminates_suspended_executable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Frozen preparation parent death Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    config = root / "atlas.yaml"
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", config)
    run_id = "frozen-preparation-parent-death"
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
    approval_hash = hashlib.sha256(approval_path.read_bytes()).hexdigest()
    before_approval = approval_path.read_bytes()
    before_config = config.read_bytes()
    worker = root / "bundle" / "DiffeoForgeReferencePreparationWorker.exe"
    worker.parent.mkdir()
    shutil.copyfile(sys.executable, worker)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/audit_frozen_reference_preparation_parent_death.py",
            str(worker),
            str(approval_path),
            str(config),
            "--expect-request-sha256",
            approval_hash,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["schema_version"] == "0.1"
    assert evidence["status"] == (
        "frozen_preparation_worker_terminated_after_hard_parent_death_before_request"
    )
    assert evidence["controller_exit_code"] == 73
    assert evidence["job_assignment_completed"] is True
    assert evidence["worker_started_suspended"] is True
    assert evidence["worker_stopped"] is True
    assert evidence["request_delivered"] is False
    assert evidence["destination_exists"] is False
    assert evidence["private_stage_count"] == 0
    assert evidence["approval_request_sha256"] == approval_hash
    assert evidence["approved_plan_fingerprint"] == (
        approval["approval"]["approved_plan_fingerprint"]
    )
    assert evidence["worker"] == {
        "basename": "DiffeoForgeReferencePreparationWorker.exe",
        "executable": str(worker.resolve()),
    }
    assert evidence["engine_execution_started"] is False
    destination = Path(plan["run"]["destination"])
    assert not destination.exists()
    assert not tuple(
        destination.parent.glob(f".diffeoforge-preparing-{run_id}-*")
    )
    assert approval_path.read_bytes() == before_approval
    assert config.read_bytes() == before_config


def test_hard_parent_exit_terminates_controller_worker(tmp_path: Path) -> None:
    root = tmp_path / "Parent death Käfer"
    root.mkdir()
    config = root / "modern.yaml"
    config.write_text("test config\n", encoding="utf-8")
    pid_path = root / "worker.pid"
    stderr_path = root / "parent.stderr"
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
            "import os,sys",
            "from pathlib import Path",
            "from diffeoforge.desktop.worker_controller import DesktopWorkerController",
            "from diffeoforge.desktop.worker_protocol import DesktopWorkerRequest",
            f"request=DesktopWorkerRequest.from_dict({request.as_dict()!r})",
            (
                "controller=DesktopWorkerController(request, "
                f"worker_command=(sys.executable,'-c',{worker_code!r}), cwd={str(ROOT)!r})"
            ),
            "def hard_exit_after_started(event):",
            "    assert event.kind == 'started'",
            "    process=controller._process",
            "    assert process is not None",
            (
                f"    observed=Path({str(pid_path)!r}).read_text(encoding='ascii')"
            ),
            "    assert observed.isdecimal(), observed",
            "    os._exit(73)",
            "controller.run(event_callback=hard_exit_after_started)",
        )
    )
    with stderr_path.open("w", encoding="utf-8", newline="\n") as stderr_handle:
        parent = subprocess.run(
            [sys.executable, "-c", launcher_code],
            cwd=ROOT,
            check=False,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            text=True,
        )

    assert parent.returncode == 73, stderr_path.read_text(encoding="utf-8")
    worker_pid = int(pid_path.read_text(encoding="ascii"))
    try:
        assert _wait_until_stopped(worker_pid)
    finally:
        if _process_is_active(worker_pid):
            _terminate_process_id(worker_pid)
    assert not request.destination.exists()
