from __future__ import annotations

from pathlib import Path

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
