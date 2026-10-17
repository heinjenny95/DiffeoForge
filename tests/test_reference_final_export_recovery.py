from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge.config import ConfigurationError

spec = importlib.util.spec_from_file_location(
    "final_export_tool", Path(__file__).parents[1] / "tools/reference_final_export_recovery.py"
)
assert spec is not None and spec.loader is not None
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_iteration_scalar_never_unpickles(tmp_path, monkeypatch):
    path = tmp_path / "state.p"
    path.write_bytes(pickle.dumps({"current_parameters": {}, "current_iteration": 76}))
    monkeypatch.setattr(pickle, "loads", lambda *a, **k: pytest.fail("Unpickling forbidden"))
    assert tool.checkpoint_iteration(path) == 76


@pytest.mark.parametrize("state", [b"broken", pickle.dumps({"current_iteration": 76}) + b"extra"])
def test_incomplete_or_trailing_checkpoint_rejected(tmp_path, state):
    path = tmp_path / "state.p"
    path.write_bytes(state)
    with pytest.raises(ConfigurationError):
        tool.checkpoint_iteration(path)


def test_tolerance_stop_must_match_checkpoint_iteration(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output/native_info.log").write_text(
        "----- Iteration: 75 -----\nTolerance threshold met. Stopping the optimization process.\n"
    )
    assert tool.export_stop_evidence(tmp_path, 76, 300)["native_stop"] == "native_tolerance"
    with pytest.raises(ConfigurationError):
        tool.export_stop_evidence(tmp_path, 80, 300)


def test_capped_export_requires_export_start_and_not_line_search_failure(tmp_path):
    (tmp_path / "output").mkdir()
    log = tmp_path / "output/native_info.log"
    text = "----- Iteration: 4 -----\nDiffeoForge final mesh export started: 2 specimens\n"
    log.write_text(text)
    assert tool.export_stop_evidence(tmp_path, 4, 4)["native_stop"] == "iteration_limit"
    log.write_text(text + "Number of line search loops exceeded. Stopping.\n")
    with pytest.raises(ConfigurationError):
        tool.export_stop_evidence(tmp_path, 4, 4)


def test_storage_counts_all_flows_and_an_input_copy(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "input").mkdir()
    (tmp_path / "output/Atlas__flow__surface.vtk").write_bytes(b"x" * 100)
    (tmp_path / "input/template.vtk").write_bytes(b"x" * 30)
    manifest = {
        "input_count": {"subjects": 2},
        "effective_config": {"model": {"deformation": {"timepoints": 3}}},
    }
    assert tool.required_export_space(tmp_path, manifest) == 990 + 30 + 2 * 1024**3


def test_insufficient_space_does_not_create_or_mutate_a_run(tmp_path, monkeypatch):
    (tmp_path / "output").mkdir()
    (tmp_path / "input").mkdir()
    checkpoint = tmp_path / "output/state.p"
    checkpoint.write_bytes(pickle.dumps({"current_iteration": 4}))
    (tmp_path / "output/native_info.log").write_text(
        "----- Iteration: 4 -----\nDiffeoForge final mesh export started: 2 specimens\n"
    )
    (tmp_path / "output/Atlas__flow__surface.vtk").write_bytes(b"x" * 100)
    manifest = {
        "input_count": {"subjects": 2},
        "effective_config": {
            "optimization": {"max_iterations": 4},
            "model": {"deformation": {"timepoints": 3}},
        },
    }
    monkeypatch.setattr(
        tool,
        "inspect_resume_source",
        lambda p: SimpleNamespace(checkpoint_path=checkpoint, manifest=manifest),
    )
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda p: SimpleNamespace(free=1))
    monkeypatch.setattr(tool, "prepare_resume_run", lambda *a, **k: pytest.fail("Must not prepare"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ConfigurationError, match="free bytes"):
        tool.prepare_final_export(tmp_path, run_id="export")
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
