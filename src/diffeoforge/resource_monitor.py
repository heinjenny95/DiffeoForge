"""Best-effort live resource observations with explicit attribution boundaries."""

from __future__ import annotations

import math
import shutil
import subprocess
from typing import Any

from diffeoforge.subprocess_policy import hidden_windows_process_kwargs


class ProcessResourceMonitor:
    """Sample one backend process tree without making resource guarantees."""

    def __init__(self, process_id: int, *, requested_device: str) -> None:
        if isinstance(process_id, bool) or int(process_id) < 1:
            raise ValueError("process_id must be a positive integer")
        if requested_device not in {"cpu", "cuda"}:
            raise ValueError("requested_device must be cpu or cuda")
        self.process_id = int(process_id)
        self.requested_device = requested_device
        self._psutil: Any | None = None
        self._process: Any | None = None
        self._psutil_error: str | None = None
        try:
            import psutil

            self._psutil = psutil
            self._process = psutil.Process(self.process_id)
            self._prime_cpu_tree()
        except Exception as error:
            self._psutil_error = f"{type(error).__name__}: {error}"

    def _process_tree(self) -> tuple[Any, ...]:
        if self._process is None or self._psutil is None:
            return ()
        try:
            return (self._process, *self._process.children(recursive=True))
        except self._psutil.Error:
            return ()

    def _prime_cpu_tree(self) -> None:
        for process in self._process_tree():
            try:
                process.cpu_percent(interval=None)
            except self._psutil.Error:
                continue

    @staticmethod
    def _finite_nonnegative(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number >= 0 else None

    def _process_observation(self) -> dict[str, object]:
        if self._psutil is None:
            return {
                "status": "unavailable",
                "reason": self._psutil_error or "psutil is not installed",
                "process_count": None,
                "cpu_percent": None,
                "rss_bytes": None,
                "system_memory_percent": None,
                "system_memory_available_bytes": None,
                "system_memory_total_bytes": None,
            }
        processes = self._process_tree()
        if not processes:
            return {
                "status": "unavailable",
                "reason": "backend process tree is no longer observable",
                "process_count": None,
                "cpu_percent": None,
                "rss_bytes": None,
                "system_memory_percent": None,
                "system_memory_available_bytes": None,
                "system_memory_total_bytes": None,
            }
        cpu = 0.0
        rss = 0
        observed = 0
        for process in processes:
            try:
                candidate_cpu = self._finite_nonnegative(
                    process.cpu_percent(interval=None)
                )
                memory = process.memory_info()
            except self._psutil.Error:
                continue
            if candidate_cpu is not None:
                cpu += candidate_cpu
            rss += max(0, int(memory.rss))
            observed += 1
        try:
            virtual_memory = self._psutil.virtual_memory()
            system_percent = self._finite_nonnegative(virtual_memory.percent)
            available = max(0, int(virtual_memory.available))
            total = max(0, int(virtual_memory.total))
        except self._psutil.Error:
            system_percent = None
            available = total = None
        return {
            "status": "observed" if observed else "unavailable",
            "reason": None if observed else "backend processes disappeared during sampling",
            "process_count": observed or None,
            "cpu_percent": cpu if observed else None,
            "rss_bytes": rss if observed else None,
            "system_memory_percent": system_percent,
            "system_memory_available_bytes": available,
            "system_memory_total_bytes": total,
        }

    def _gpu_observation(self) -> dict[str, object]:
        if self.requested_device != "cuda":
            return {
                "status": "not_requested",
                "scope": "none",
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "reason": "CPU execution was selected",
            }
        executable = shutil.which("nvidia-smi")
        if executable is None:
            return {
                "status": "unavailable",
                "scope": "device_total_not_attributed_to_run",
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "reason": "nvidia-smi is not available on the host PATH",
            }
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
                **hidden_windows_process_kwargs(),
            )
            first = completed.stdout.splitlines()[0]
            utilization, used_mib, total_mib = (
                self._finite_nonnegative(value.strip()) for value in first.split(",")
            )
            if (
                completed.returncode != 0
                or utilization is None
                or used_mib is None
                or total_mib is None
            ):
                raise ValueError("nvidia-smi returned no complete numeric device row")
        except (OSError, subprocess.SubprocessError, IndexError, ValueError) as error:
            return {
                "status": "unavailable",
                "scope": "device_total_not_attributed_to_run",
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "reason": f"{type(error).__name__}: {error}",
            }
        mib = 1024**2
        return {
            "status": "observed",
            "scope": "device_total_not_attributed_to_run",
            "utilization_percent": utilization,
            "memory_used_bytes": round(used_mib * mib),
            "memory_total_bytes": round(total_mib * mib),
            "reason": (
                "Device-wide NVIDIA telemetry; WSL/container process attribution is not "
                "claimed for this run"
            ),
        }

    def sample(self) -> dict[str, object]:
        """Return one JSON-compatible observation; failures remain descriptive."""

        try:
            process = self._process_observation()
        except Exception as error:
            process = {
                "status": "unavailable",
                "reason": f"{type(error).__name__}: {error}",
                "process_count": None,
                "cpu_percent": None,
                "rss_bytes": None,
                "system_memory_percent": None,
                "system_memory_available_bytes": None,
                "system_memory_total_bytes": None,
            }
        try:
            gpu = self._gpu_observation()
        except Exception as error:
            gpu = {
                "status": "unavailable",
                "scope": "device_total_not_attributed_to_run",
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "reason": f"{type(error).__name__}: {error}",
            }
        return {
            "backend_process_id": self.process_id,
            "requested_device": self.requested_device,
            "process_tree": process,
            "gpu": gpu,
            "boundary": (
                "CPU and RSS are observations of the currently visible launcher process "
                "tree and can miss work hidden inside WSL or a container. CUDA values, when "
                "available, are whole-device observations and are not attributed solely to "
                "this atlas. These values are not peak-memory guarantees or cost estimates."
            ),
        }
