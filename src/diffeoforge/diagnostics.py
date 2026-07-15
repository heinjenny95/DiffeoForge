"""Read-only first-run diagnostics for the DiffeoForge reference workflow."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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

    @property
    def ready(self) -> bool:
        """Return whether no blocking check failed."""

        return self.status != "blocked"

    def as_dict(self) -> dict[str, Any]:
        """Return a stable representation for CLI JSON output."""

        return {
            "status": self.status,
            "workspace": self.workspace,
            "engine": self.engine,
            "image": self.image,
            "checks": [asdict(check) for check in self.checks],
        }


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
    )
