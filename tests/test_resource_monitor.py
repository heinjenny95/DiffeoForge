from __future__ import annotations

import os

import pytest

from diffeoforge.resource_monitor import ProcessResourceMonitor


def test_cpu_resource_monitor_has_explicit_attribution_boundary() -> None:
    monitor = ProcessResourceMonitor(os.getpid(), requested_device="cpu")

    snapshot = monitor.sample()

    assert snapshot["backend_process_id"] == os.getpid()
    assert snapshot["requested_device"] == "cpu"
    assert snapshot["process_tree"]["status"] in {"observed", "unavailable"}
    assert snapshot["gpu"]["status"] == "not_requested"
    assert "can miss work hidden inside WSL or a container" in snapshot["boundary"]


@pytest.mark.parametrize(("pid", "device"), [(0, "cpu"), (1, "automatic")])
def test_resource_monitor_rejects_ambiguous_target(pid: int, device: str) -> None:
    with pytest.raises(ValueError):
        ProcessResourceMonitor(pid, requested_device=device)
