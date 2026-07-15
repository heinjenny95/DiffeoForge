from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from diffeoforge import diagnostics


def test_doctor_reports_ready_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _engine: "/usr/bin/docker")
    monkeypatch.setattr(diagnostics.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(diagnostics.os, "access", lambda _path, _mode: True)
    monkeypatch.setattr(diagnostics, "_physical_memory_bytes", lambda: 128 * 1024**3)
    monkeypatch.setattr(
        diagnostics.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=200 * 1024**3),
    )

    def fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        stdout = '"sha256:abc123"\n' if "inspect" in argv else "27.5.1\n"
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(diagnostics, "_run_command", fake_run)

    report = diagnostics.run_doctor(tmp_path)

    assert report.status == "ready"
    assert report.ready is True
    assert all(check.status == "pass" for check in report.checks)
    assert report.as_dict()["checks"][-1]["summary"] == "sha256:abc123"


def test_doctor_explains_missing_container_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _engine: None)
    monkeypatch.setattr(diagnostics.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(diagnostics.os, "access", lambda _path, _mode: True)
    monkeypatch.setattr(diagnostics, "_physical_memory_bytes", lambda: 32 * 1024**3)
    monkeypatch.setattr(
        diagnostics.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=50 * 1024**3),
    )

    report = diagnostics.run_doctor(tmp_path)
    checks = {check.check_id: check for check in report.checks}

    assert report.status == "blocked"
    assert report.ready is False
    assert checks["container_cli"].status == "fail"
    assert "Docker Desktop" in (checks["container_cli"].guidance or "")
    assert checks["container_daemon"].status == "skip"
    assert checks["reference_image"].status == "skip"
