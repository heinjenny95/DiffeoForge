from __future__ import annotations

import json
import subprocess

from diffeoforge import reference_runtime


def _completed(argv: list[str], returncode: int = 0, output: bytes = b""):
    return subprocess.CompletedProcess(argv, returncode, stdout=output, stderr=b"")


def test_probe_wsl_launcher_verifies_exact_deformetrica_version(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "DiffeoForge-Reference-4.3",
        "executable": "/opt/diffeoforge/reference/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        reference_runtime,
        "installed_wsl_distributions",
        lambda: ("DiffeoForge-Reference-4.3",),
    )

    def fake_run(arguments: list[str], *, timeout: int = 30):
        if arguments[-1] == "--help":
            return _completed(arguments, output=b"Deformetrica 4.3.0\n")
        return _completed(arguments)

    monkeypatch.setattr(reference_runtime, "_run_wsl", fake_run)

    probe = reference_runtime.probe_wsl_launcher(launcher)

    assert probe.ready is True
    assert probe.version == "4.3.0"
    assert probe.managed is True


def test_probe_wsl_launcher_rejects_wrong_version(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        reference_runtime, "installed_wsl_distributions", lambda: ("Ubuntu",)
    )

    def fake_run(arguments: list[str], *, timeout: int = 30):
        if arguments[-1] == "--help":
            return _completed(arguments, output=b"Deformetrica 4.2.0\n")
        return _completed(arguments)

    monkeypatch.setattr(reference_runtime, "_run_wsl", fake_run)

    probe = reference_runtime.probe_wsl_launcher(launcher)

    assert probe.ready is False
    assert "4.3.0" in (probe.guidance or "")


def test_probe_reference_gpu_verifies_keops_cuda_prerequisites(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)

    def fake_run(arguments: list[str], *, timeout: int = 30):
        assert "CUDA_VISIBLE_DEVICES=0" in arguments
        assert "CC=/usr/bin/gcc-12" in arguments
        assert "CXX=/usr/bin/g++-12" in arguments
        assert "/home/researcher/deformetrica/bin/python" in arguments
        payload = {
            "available": True,
            "device_count": 1,
            "device_name": "NVIDIA GeForce RTX 4080",
            "compute_capability": "8.9",
            "nvcc": "/usr/bin/nvcc",
            "gcc12": "/usr/bin/gcc-12",
            "gxx12": "/usr/bin/g++-12",
            "smoke_ok": True,
        }
        return _completed(
            arguments,
            output=(
                "compile output\nDIFFEOFORGE_GPU_PROBE="
                + json.dumps(payload)
                + "\n"
            ).encode("utf-8"),
        )

    monkeypatch.setattr(reference_runtime, "_run_wsl", fake_run)

    probe = reference_runtime.probe_reference_gpu(launcher)

    assert probe.available is True
    assert probe.device_name == "NVIDIA GeForce RTX 4080"
    assert probe.compute_capability == "8.9"
    assert probe.cuda_compiler == "/usr/bin/nvcc"
    assert probe.host_cpp_compiler == "/usr/bin/g++-12"


def test_probe_reference_gpu_requires_cuda_compiler(monkeypatch) -> None:
    launcher = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        reference_runtime,
        "_run_wsl",
        lambda arguments, **_kwargs: _completed(
            arguments,
            output=json.dumps(
                {
                    "available": True,
                    "device_count": 1,
                    "device_name": "GPU",
                    "compute_capability": "8.9",
                    "nvcc": None,
                    "gcc12": "/usr/bin/gcc-12",
                    "gxx12": "/usr/bin/g++-12",
                    "smoke_ok": False,
                }
            ).join(("DIFFEOFORGE_GPU_PROBE=", "\n")).encode("utf-8"),
        ),
    )

    probe = reference_runtime.probe_reference_gpu(launcher)

    assert probe.available is False
    assert "CUDA compiler" in probe.summary


def test_preferred_launcher_reuses_verified_same_owner_alpha_runtime(monkeypatch) -> None:
    managed = reference_runtime.managed_wsl_launcher()
    legacy = {
        "type": "wsl",
        "distribution": "Ubuntu",
        "executable": "/home/researcher/deformetrica/bin/deformetrica",
    }
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(
        reference_runtime, "installed_wsl_distributions", lambda: ("Ubuntu",)
    )
    monkeypatch.setattr(
        reference_runtime,
        "_default_home_deformetrica",
        lambda distribution: legacy["executable"],
    )

    def fake_probe(launcher, *, expected_version="4.3.0"):
        ready = dict(launcher) == legacy
        return reference_runtime.ReferenceRuntimeProbe(
            dict(launcher), ready, "4.3.0" if ready else None, "test"
        )

    monkeypatch.setattr(reference_runtime, "probe_wsl_launcher", fake_probe)

    assert reference_runtime.select_preferred_reference_launcher() == legacy
    assert reference_runtime.select_preferred_reference_launcher() != managed


def test_preferred_launcher_falls_back_to_installer_owned_identity(monkeypatch) -> None:
    monkeypatch.setattr(reference_runtime.os, "name", "nt")
    monkeypatch.setattr(reference_runtime, "installed_wsl_distributions", lambda: ())
    monkeypatch.setattr(
        reference_runtime,
        "probe_wsl_launcher",
        lambda launcher, **_kwargs: reference_runtime.ReferenceRuntimeProbe(
            dict(launcher), False, None, "missing"
        ),
    )

    assert (
        reference_runtime.select_preferred_reference_launcher()
        == reference_runtime.managed_wsl_launcher()
    )
