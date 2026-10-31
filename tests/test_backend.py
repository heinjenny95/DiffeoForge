from __future__ import annotations

from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

import diffeoforge.backends.deformetrica_reference as backend
from diffeoforge.backends.deformetrica_reference import (
    build_command,
    build_shooting_command,
)
from diffeoforge.config import ConfigurationError


@pytest.mark.parametrize(
    ("source", "expected"),
    [(r"C:\Project with spaces\Ä", "/mnt/c/Project with spaces/Ä"), ("D:/run", "/mnt/d/run")],
)
def test_wsl_path_translation_is_explicit_on_every_host(monkeypatch, source, expected):
    monkeypatch.setattr(
        backend, "_command_run_directory", lambda path, **kwargs: PureWindowsPath(source)
    )
    assert backend._windows_to_wsl(Path("unused")) == expected


def test_wsl_path_translation_rejects_unmapped_network_share(monkeypatch):
    monkeypatch.setattr(
        backend,
        "_command_run_directory",
        lambda path, **kwargs: PureWindowsPath(r"\\server\share\run"),
    )
    with pytest.raises(ConfigurationError, match="Cannot translate"):
        backend._windows_to_wsl(Path("unused"))


def test_container_command_is_offline_read_only_and_mounts_run(tmp_path: Path) -> None:
    config = {
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cpu",
            "threads": 6,
            "verbosity": "INFO",
            "launcher": {
                "type": "container",
                "engine": "docker",
                "image": "diffeoforge-deformetrica:4.3.0-cpu",
            },
        },
        "output": {"retain_flow_meshes": True},
    }

    command = build_command(config, tmp_path)

    assert command.argv[:7] == (
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:rw,exec,nosuid,size=1g",
    )
    assert f"type=bind,source={tmp_path.resolve()},target=/work" in command.argv
    omp_index = command.argv.index("OMP_NUM_THREADS=6")
    assert command.argv[omp_index - 1] == "--env"
    assert "diffeoforge-deformetrica:4.3.0-cpu" in command.argv
    assert command.argv[-1] == "INFO"
    assert command.environment["USE_CUDA"] == "0"
    assert command.environment["CUDA_VISIBLE_DEVICES"] == "-1"


def test_wsl_gpu_command_exposes_one_cuda_device_and_records_kernel_mode(
    monkeypatch, tmp_path: Path
) -> None:
    config = {
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cuda",
            "threads": 16,
            "verbosity": "INFO",
            "launcher": {
                "type": "wsl",
                "distribution": "Ubuntu",
                "executable": "/home/researcher/deformetrica/bin/deformetrica",
            },
        },
        "output": {"retain_flow_meshes": True},
    }
    # Isolate the simulated platform from pathlib and pytest's real OS state.
    monkeypatch.setattr(backend, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(backend.shutil, "which", lambda command: command)
    monkeypatch.setattr(backend, "_windows_to_wsl", lambda path, **kwargs: "/mnt/c/synthetic-run")

    command = build_command(config, tmp_path)

    assert command.environment == {
        "OMP_NUM_THREADS": "16",
        "CUDA_VISIBLE_DEVICES": "0",
        "CC": "/usr/bin/gcc-12",
        "CXX": "/usr/bin/g++-12",
        "CUDAHOSTCXX": "/usr/bin/g++-12",
    }
    assert "USE_CUDA=1" not in command.argv
    assert command.argv[command.argv.index("env") + 1 : command.argv.index("env") + 3] == (
        "-u",
        "USE_CUDA",
    )
    assert "CUDA_VISIBLE_DEVICES=0" in command.argv
    assert command.argv[command.argv.index("--cd") + 1] == "/mnt/c/synthetic-run"
    assert command.argv[-1] == "INFO"


def test_shooting_command_reuses_runtime_without_dataset_estimation(
    tmp_path: Path,
) -> None:
    config = {
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cpu",
            "threads": 4,
            "verbosity": "WARNING",
            "launcher": {
                "type": "native",
                "executable": "deformetrica",
            },
        },
        "output": {"retain_flow_meshes": True},
    }

    command = build_shooting_command(config, tmp_path)

    assert command.argv == (
        "deformetrica",
        "compute",
        "engine/model.xml",
        "-p",
        "engine/optimization_parameters.xml",
        "--output=output",
        "-v",
        "WARNING",
    )
    assert "data_set.xml" not in command.argv
    assert command.working_directory == str(tmp_path.resolve())
    assert command.environment == {
        "OMP_NUM_THREADS": "4",
        "CUDA_VISIBLE_DEVICES": "-1",
        "USE_CUDA": "0",
        "MKL_CBWR": "COMPATIBLE",
    }


@pytest.mark.parametrize("operation", [build_command, build_shooting_command])
@pytest.mark.parametrize("launcher_type", ["native", "wsl", "container"])
def test_cpu_compatibility_is_scoped_and_recorded_for_each_launcher(
    operation, launcher_type, monkeypatch, tmp_path
):
    monkeypatch.setenv("MKL_CBWR", "AUTO")
    config = {
        "runtime": {
            "backend": "deformetrica_reference",
            "device": "cpu",
            "threads": 4,
            "verbosity": "INFO",
            "launcher": {
                "type": launcher_type,
                "executable": "deformetrica",
                "distribution": "Ubuntu",
                "engine": "docker",
                "image": "frozen",
            },
        },
        "output": {"retain_flow_meshes": True},
    }
    if launcher_type == "wsl":
        monkeypatch.setattr(backend, "os", SimpleNamespace(name="nt"))
        monkeypatch.setattr(backend.shutil, "which", lambda command: command)
        monkeypatch.setattr(backend, "_windows_to_wsl", lambda *a, **kw: "/mnt/c/test")
    command = operation(config, tmp_path)
    assert command.as_manifest()["environment"]["MKL_CBWR"] == "COMPATIBLE"
    if launcher_type != "native":
        assert command.argv.count("MKL_CBWR=COMPATIBLE") == 1
        assert "MKL_CBWR=AUTO" not in command.argv
    import os

    assert os.environ["MKL_CBWR"] == "AUTO"
