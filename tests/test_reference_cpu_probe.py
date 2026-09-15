from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools/probe_reference_cpu.py"
spec = importlib.util.spec_from_file_location("reference_cpu_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_probe_is_frozen_python38_compatible():
    ast.parse(SCRIPT.read_text(), feature_version=(3, 8))


def test_probe_accepts_only_six_hash_checked_public_inputs():
    paths = probe.checked_meshes(ROOT)
    assert len(paths) == 6
    assert set(paths) == {"template.vtk", *(f"subject-{i:02}.vtk" for i in range(1, 6))}


@pytest.mark.parametrize("target", ["dataset-manifest.json", "subject-01.vtk"])
def test_probe_rejects_modified_inputs(tmp_path, target):
    root = tmp_path / "examples/synthetic/meshes"
    shutil.copytree(ROOT / "examples/synthetic/meshes", root)
    with (root / target).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError):
        probe.checked_meshes(tmp_path)


def test_backend_probe_records_cpu_and_only_allowlisted_numeric_environment(monkeypatch, tmp_path):
    from diffeoforge.runs import _probe_backend_environment

    monkeypatch.setenv("MKL_CBWR", "AUTO")
    monkeypatch.setenv("PRIVATE_PROBE_TEST", "must-not-be-reported")
    metadata = tmp_path / "deformetrica-4.3.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: deformetrica\nVersion: 4.3.0\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    report = _probe_backend_environment(
        {
            "runtime": {
                "device": "cpu",
                "threads": 4,
                "launcher": {"type": "native", "executable": sys.executable},
            }
        }
    )
    assert report["probe_status"] == "verified"
    assert report["cpu_model"]
    assert report["probe_numerical_environment"]["MKL_CBWR"] == "COMPATIBLE"
    assert report["probe_numerical_environment"]["OMP_NUM_THREADS"] == "4"
    assert set(report["probe_numerical_environment"]) == {
        "MKL_CBWR",
        "MKL_ENABLE_INSTRUCTIONS",
        "MKL_DEBUG_CPU_TYPE",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
    }
    assert "must-not-be-reported" not in str(report)


@pytest.mark.parametrize("launcher_type", ["wsl", "container"])
def test_cpu_probe_passes_same_explicit_environment_inside_guest(launcher_type, monkeypatch):
    import json
    from types import SimpleNamespace

    import diffeoforge.runs as runs
    from diffeoforge.backends.deformetrica_reference import reference_process_environment

    config = {
        "runtime": {
            "device": "cpu",
            "threads": 6,
            "launcher": {
                "type": launcher_type,
                "distribution": "Ubuntu",
                "executable": "/runtime/deformetrica",
                "engine": "docker",
                "image": "frozen",
            },
        }
    }
    calls = []

    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = (
            [{"Id": "sha256:test"}]
            if argv[1:3] == ["image", "inspect"]
            else {"packages": {"deformetrica": "4.3.0"}}
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(runs.subprocess, "run", invoke)
    assert runs._probe_backend_environment(config)["probe_status"] == "verified"
    argv, kwargs = calls[-1]
    for key, value in reference_process_environment(config).items():
        assert argv.count(f"{key}={value}") == 1
        assert kwargs["env"][key] == value
        if launcher_type == "container":
            assert argv[argv.index(f"{key}={value}") - 1] == "--env"
