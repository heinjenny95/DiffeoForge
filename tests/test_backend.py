from __future__ import annotations

from pathlib import Path

import diffeoforge.backends.deformetrica_reference as backend
from diffeoforge.backends.deformetrica_reference import build_command


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
    monkeypatch.setattr(backend.os, "name", "nt")
    monkeypatch.setattr(backend.shutil, "which", lambda command: command)

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
    assert command.argv[-1] == "INFO"
