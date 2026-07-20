"""Read-only first-run diagnostics for the DiffeoForge reference workflow."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from diffeoforge.reference_runtime import (
    EXPECTED_DEFORMETRICA_VERSION,
    launcher_identity,
    probe_wsl_launcher,
)

DEFAULT_CONTAINER_IMAGE = "diffeoforge-deformetrica:4.3.0-cpu"
MINIMUM_MEMORY_BYTES = 8 * 1024**3
MINIMUM_DISK_BYTES = 5 * 1024**3


@dataclass(frozen=True)
class DoctorCheck:
    """One independently observable environment check."""

    check_id: str
    label: str
    status: str
    summary: str
    guidance: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Complete, JSON-serializable doctor result."""

    status: str
    workspace: str
    engine: str
    image: str
    checks: tuple[DoctorCheck, ...]
    launcher: Mapping[str, str] | None = None

    @property
    def ready(self) -> bool:
        """Return whether no blocking check failed."""

        return self.status != "blocked"

    def as_dict(self) -> dict[str, Any]:
        """Return a stable representation for CLI JSON output."""

        result = {
            "status": self.status,
            "workspace": self.workspace,
            "engine": self.engine,
            "image": self.image,
            "checks": [asdict(check) for check in self.checks],
        }
        if self.launcher is not None:
            result["launcher"] = dict(self.launcher)
        return result


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _physical_memory_bytes() -> int | None:
    """Return total physical memory using only the Python standard library."""

    if sys.platform == "win32":
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        try:
            succeeded = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        except (AttributeError, OSError):
            return None
        return int(status.ullTotalPhys) if succeeded else None

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return None
    return pages * page_size


def _run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f} GiB"


def _command_detail(completed: subprocess.CompletedProcess[str]) -> str:
    value = completed.stdout.strip() or completed.stderr.strip()
    return value.splitlines()[0] if value else f"exit code {completed.returncode}"


def run_doctor(
    workspace: Path | str = ".",
    *,
    engine: str = "docker",
    image: str = DEFAULT_CONTAINER_IMAGE,
) -> DoctorReport:
    """Inspect the host and frozen backend without modifying either one."""

    workspace_path = Path(workspace).expanduser().resolve()
    checks: list[DoctorCheck] = []

    python_supported = sys.version_info >= (3, 11)
    checks.append(
        DoctorCheck(
            check_id="python",
            label="Host Python",
            status="pass" if python_supported else "fail",
            summary=platform.python_version(),
            guidance=None if python_supported else "Install Python 3.11 or newer.",
        )
    )
    checks.append(
        DoctorCheck(
            check_id="platform",
            label="Operating system",
            status="pass",
            summary=platform.platform(),
        )
    )

    cpu_count = os.cpu_count()
    cpu_status = "pass" if cpu_count is not None and cpu_count >= 2 else "warning"
    checks.append(
        DoctorCheck(
            check_id="cpu",
            label="Logical CPUs",
            status=cpu_status,
            summary=str(cpu_count) if cpu_count is not None else "unknown",
            guidance=(
                None
                if cpu_status == "pass"
                else "Atlas estimation is likely to be slow with fewer than two logical CPUs."
            ),
        )
    )

    memory = _physical_memory_bytes()
    if memory is None:
        memory_status = "warning"
        memory_summary = "could not be detected"
        memory_guidance = "Confirm that the machine has enough RAM for the intended meshes."
    else:
        memory_status = "pass" if memory >= MINIMUM_MEMORY_BYTES else "warning"
        memory_summary = _gib(memory)
        memory_guidance = (
            None
            if memory_status == "pass"
            else "At least 8 GiB is recommended even for small exploratory runs."
        )
    checks.append(
        DoctorCheck(
            check_id="memory",
            label="Physical memory",
            status=memory_status,
            summary=memory_summary,
            guidance=memory_guidance,
        )
    )

    if workspace_path.is_dir():
        writable = os.access(workspace_path, os.W_OK)
        checks.append(
            DoctorCheck(
                check_id="workspace",
                label="Workspace",
                status="pass" if writable else "fail",
                summary=str(workspace_path),
                guidance=None if writable else "Choose a writable project directory.",
            )
        )
        try:
            free_disk = shutil.disk_usage(workspace_path).free
        except OSError:
            free_disk = None
        if free_disk is None:
            disk_status = "warning"
            disk_summary = "could not be detected"
            disk_guidance = "Confirm free disk space before starting an atlas."
        else:
            disk_status = "pass" if free_disk >= MINIMUM_DISK_BYTES else "warning"
            disk_summary = f"{_gib(free_disk)} free"
            disk_guidance = (
                None
                if disk_status == "pass"
                else "Keep at least 5 GiB free for staged inputs, logs, and outputs."
            )
        checks.append(
            DoctorCheck(
                check_id="disk",
                label="Free disk space",
                status=disk_status,
                summary=disk_summary,
                guidance=disk_guidance,
            )
        )
    else:
        checks.extend(
            (
                DoctorCheck(
                    check_id="workspace",
                    label="Workspace",
                    status="fail",
                    summary=f"directory does not exist: {workspace_path}",
                    guidance="Create the project directory or pass an existing --workspace.",
                ),
                DoctorCheck(
                    check_id="disk",
                    label="Free disk space",
                    status="skip",
                    summary="not checked because the workspace is missing",
                ),
            )
        )

    executable = shutil.which(engine)
    if executable is None:
        checks.extend(
            (
                DoctorCheck(
                    check_id="container_cli",
                    label="Container command",
                    status="fail",
                    summary=f"{engine!r} is not available on PATH",
                    guidance=(
                        "Install and start Docker Desktop or another Docker-compatible engine."
                    ),
                ),
                DoctorCheck(
                    check_id="container_daemon",
                    label="Container service",
                    status="skip",
                    summary="not checked because the container command is missing",
                ),
                DoctorCheck(
                    check_id="reference_image",
                    label="Reference image",
                    status="skip",
                    summary="not checked because the container command is missing",
                ),
            )
        )
    else:
        checks.append(
            DoctorCheck(
                check_id="container_cli",
                label="Container command",
                status="pass",
                summary=executable,
            )
        )
        try:
            version = _run_command([engine, "version", "--format", "{{.Server.Version}}"])
        except (OSError, subprocess.TimeoutExpired) as error:
            version = None
            daemon_detail = str(error)
        else:
            daemon_detail = _command_detail(version)
        daemon_ready = version is not None and version.returncode == 0
        checks.append(
            DoctorCheck(
                check_id="container_daemon",
                label="Container service",
                status="pass" if daemon_ready else "fail",
                summary=daemon_detail,
                guidance=(
                    None
                    if daemon_ready
                    else "Start Docker Desktop and wait until its engine reports ready."
                ),
            )
        )

        if not daemon_ready:
            checks.append(
                DoctorCheck(
                    check_id="reference_image",
                    label="Reference image",
                    status="skip",
                    summary="not checked because the container service is unavailable",
                )
            )
        else:
            try:
                inspected = _run_command(
                    [engine, "image", "inspect", image, "--format", "{{json .Id}}"]
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                inspected = None
                image_detail = str(error)
            else:
                image_detail = _command_detail(inspected)
                try:
                    image_detail = json.loads(image_detail)
                except json.JSONDecodeError:
                    pass
            image_ready = inspected is not None and inspected.returncode == 0
            checks.append(
                DoctorCheck(
                    check_id="reference_image",
                    label="Reference image",
                    status="pass" if image_ready else "fail",
                    summary=str(image_detail),
                    guidance=(
                        None
                        if image_ready
                        else "Build the pinned image using the command shown in the documentation."
                    ),
                )
            )

    statuses = {check.status for check in checks}
    overall = "blocked" if "fail" in statuses else "warning" if "warning" in statuses else "ready"
    return DoctorReport(
        status=overall,
        workspace=str(workspace_path),
        engine=engine,
        image=image,
        checks=tuple(checks),
        launcher={"type": "container", "engine": engine, "image": image},
    )


def _reference_host_checks(workspace_path: Path) -> list[DoctorCheck]:
    """Collect launcher-independent checks for the managed desktop route."""

    checks: list[DoctorCheck] = []
    python_supported = sys.version_info >= (3, 11)
    checks.append(
        DoctorCheck(
            "python",
            "Application runtime",
            "pass" if python_supported else "fail",
            f"Python {platform.python_version()}",
            None if python_supported else "Repair the DiffeoForge installation.",
        )
    )
    checks.append(DoctorCheck("platform", "Operating system", "pass", platform.platform()))
    cpu_count = os.cpu_count()
    cpu_status = "pass" if cpu_count is not None and cpu_count >= 2 else "warning"
    checks.append(
        DoctorCheck(
            "cpu",
            "Logical CPUs",
            cpu_status,
            str(cpu_count) if cpu_count is not None else "unknown",
            None
            if cpu_status == "pass"
            else "Atlas estimation is likely to be slow on this machine.",
        )
    )
    memory = _physical_memory_bytes()
    if memory is None:
        checks.append(
            DoctorCheck(
                "memory",
                "Physical memory",
                "warning",
                "could not be detected",
                "Confirm that the machine has enough RAM for the intended meshes.",
            )
        )
    else:
        memory_status = "pass" if memory >= MINIMUM_MEMORY_BYTES else "warning"
        checks.append(
            DoctorCheck(
                "memory",
                "Physical memory",
                memory_status,
                _gib(memory),
                None
                if memory_status == "pass"
                else "At least 8 GiB is recommended even for small exploratory runs.",
            )
        )
    if not workspace_path.is_dir():
        checks.extend(
            (
                DoctorCheck(
                    "workspace",
                    "Project folder",
                    "fail",
                    f"directory does not exist: {workspace_path}",
                    "Choose an existing project folder.",
                ),
                DoctorCheck(
                    "disk",
                    "Free disk space",
                    "skip",
                    "not checked because the project folder is missing",
                ),
            )
        )
        return checks
    writable = os.access(workspace_path, os.W_OK)
    checks.append(
        DoctorCheck(
            "workspace",
            "Project folder",
            "pass" if writable else "fail",
            str(workspace_path),
            None if writable else "Choose a writable project folder.",
        )
    )
    try:
        free_disk = shutil.disk_usage(workspace_path).free
    except OSError:
        free_disk = None
    if free_disk is None:
        checks.append(
            DoctorCheck(
                "disk",
                "Free disk space",
                "warning",
                "could not be detected",
                "Confirm free disk space before starting an atlas.",
            )
        )
    else:
        disk_status = "pass" if free_disk >= MINIMUM_DISK_BYTES else "warning"
        checks.append(
            DoctorCheck(
                "disk",
                "Free disk space",
                disk_status,
                f"{_gib(free_disk)} free",
                None
                if disk_status == "pass"
                else "Keep at least 5 GiB free for inputs, logs, and outputs.",
            )
        )
    return checks


def run_reference_doctor(
    workspace: Path | str,
    *,
    launcher: Mapping[str, str],
) -> DoctorReport:
    """Inspect the exact configured launcher without installing or repairing it."""

    identity = launcher_identity(launcher)
    launcher_type = identity["type"]
    if launcher_type == "container":
        return run_doctor(
            workspace,
            engine=identity["engine"],
            image=identity["image"],
        )

    workspace_path = Path(workspace).expanduser().resolve()
    checks = _reference_host_checks(workspace_path)
    if launcher_type == "wsl":
        probe = probe_wsl_launcher(identity)
        wsl_available = shutil.which("wsl.exe") is not None and os.name == "nt"
        checks.append(
            DoctorCheck(
                "wsl",
                "Windows reference subsystem",
                "pass" if wsl_available else "fail",
                "available" if wsl_available else "not available",
                None
                if wsl_available
                else "Repair the DiffeoForge reference-runtime installation.",
            )
        )
        checks.append(
            DoctorCheck(
                "reference_runtime",
                "Deformetrica reference runtime",
                "pass" if probe.ready else "fail",
                probe.summary,
                probe.guidance,
            )
        )
        descriptor = f"{identity['distribution']}:{identity['executable']}"
    else:
        executable = identity["executable"]
        resolved = (
            str(Path(executable).resolve())
            if Path(executable).is_absolute() and Path(executable).is_file()
            else shutil.which(executable)
        )
        version: str | None = None
        detail = resolved or f"executable not found: {executable}"
        if resolved is not None:
            try:
                completed = _run_command([resolved, "--help"])
            except (OSError, subprocess.TimeoutExpired) as error:
                detail = str(error)
            else:
                output = f"{completed.stdout}\n{completed.stderr}"
                if EXPECTED_DEFORMETRICA_VERSION in output and completed.returncode == 0:
                    version = EXPECTED_DEFORMETRICA_VERSION
                    detail = f"Deformetrica {version}: {resolved}"
        checks.append(
            DoctorCheck(
                "reference_runtime",
                "Deformetrica reference runtime",
                "pass" if version == EXPECTED_DEFORMETRICA_VERSION else "fail",
                detail,
                None
                if version == EXPECTED_DEFORMETRICA_VERSION
                else f"Install or select Deformetrica {EXPECTED_DEFORMETRICA_VERSION}.",
            )
        )
        descriptor = executable

    statuses = {check.status for check in checks}
    overall = "blocked" if "fail" in statuses else "warning" if "warning" in statuses else "ready"
    return DoctorReport(
        status=overall,
        workspace=str(workspace_path),
        engine=launcher_type,
        image=descriptor,
        checks=tuple(checks),
        launcher=identity,
    )
