from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import diffeoforge.desktop.modern_cuda_runtime as cuda_runtime
from diffeoforge.desktop.modern_cuda_runtime import (
    ModernCudaRuntimeError,
    discover_modern_cuda_runtime,
    probe_modern_cuda_runtime,
    verify_modern_cuda_runtime_binding,
)
from diffeoforge.modern_workflow import ENGINE_IMPLEMENTATION_VERSION


def _probe_payload(tmp_path: Path, **changes) -> dict[str, object]:
    package = tmp_path / "diffeoforge.py"
    worker = tmp_path / "worker.py"
    package.write_text("# package\n", encoding="utf-8")
    worker.write_text("# worker\n", encoding="utf-8")
    payload: dict[str, object] = {
        "torch_version": "2.11.0+cu128",
        "cuda_available": True,
        "cuda_version": "12.8",
        "device_name": "NVIDIA GeForce RTX 4080",
        "device_capability": [8, 9],
        "diffeoforge_path": str(package),
        "worker_path": str(worker),
        "engine_implementation_version": ENGINE_IMPLEMENTATION_VERSION,
    }
    payload.update(changes)
    return payload


def test_probe_binds_exact_external_cuda_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"external-python")
    payload = _probe_payload(tmp_path)
    observed: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        observed.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) + "\n", "")

    monkeypatch.setattr(cuda_runtime.subprocess, "run", fake_run)

    result = probe_modern_cuda_runtime(python)

    assert observed[0][:2] == (str(python.resolve()), "-I")
    assert result.device_name == "NVIDIA GeForce RTX 4080"
    assert result.device_capability == (8, 9)
    assert result.worker_command == (
        str(python.resolve()),
        "-I",
        "-m",
        "diffeoforge.desktop.worker",
    )
    verify_modern_cuda_runtime_binding(result)

    python.write_bytes(b"changed-external-python")
    with pytest.raises(ModernCudaRuntimeError, match="changed before worker launch"):
        verify_modern_cuda_runtime_binding(result)

    python.write_bytes(b"external-python")
    Path(result.worker_path).write_text("# changed worker\n", encoding="utf-8")
    with pytest.raises(ModernCudaRuntimeError, match="worker.*changed before worker launch"):
        verify_modern_cuda_runtime_binding(result)


def test_probe_rejects_engine_version_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"external-python")
    payload = _probe_payload(tmp_path, engine_implementation_version="different")
    monkeypatch.setattr(
        cuda_runtime.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps(payload) + "\n", ""
        ),
    )

    with pytest.raises(ModernCudaRuntimeError, match="different Modern engine"):
        probe_modern_cuda_runtime(python)


def test_discovery_tries_deterministic_candidates_until_one_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first-python.exe"
    second = tmp_path / "second-python.exe"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    payload = _probe_payload(tmp_path)
    monkeypatch.setattr(cuda_runtime, "_candidate_python_paths", lambda: (first, second))

    def fake_run(command, **_kwargs):
        if Path(command[0]) == first:
            return subprocess.CompletedProcess(command, 1, "", "no CUDA")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload) + "\n", "")

    monkeypatch.setattr(cuda_runtime.subprocess, "run", fake_run)

    assert discover_modern_cuda_runtime().python_path == second.resolve()
