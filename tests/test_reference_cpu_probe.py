from __future__ import annotations

import ast
import importlib.util
import shutil
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
