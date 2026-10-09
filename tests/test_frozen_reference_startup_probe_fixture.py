"""Require the safe frozen probe fixture to reach real cache reuse/rejection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_safe_cached_startup_probe_has_a_valid_atlas_before_adding_bad_mesh(
    tmp_path, monkeypatch, capsys,
):
    spec = importlib.util.spec_from_file_location(
        "startup_probe_fixture", ROOT / "tools/smoke_frozen_reference_execution_startup.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executable = tmp_path / "worker.exe"
    executable.write_bytes(b"not executed by this fixture test")
    calls = []

    def probe(worker, config_path, *, mismatch, timeout, expected_reused=0):
        calls.append(expected_reused)
        if expected_reused:
            # The warm host preflight must already have succeeded for template
            # plus at least two subjects. The added mesh then prevents any run.
            with pytest.raises(ValueError, match="repeated|degenerate|distinct"):
                module.collect_preflight(config_path, cache_project=config_path.parent)
        return {"saved_checks_reused": expected_reused, "engine_execution_started": False}

    monkeypatch.setattr(module, "probe", probe)
    monkeypatch.setattr(sys, "argv", [
        "probe", str(executable), str(ROOT / "examples/minimal-atlas-container.yaml"),
    ])
    assert module.main() == 0
    assert calls == [0, 0, 3]
    assert '"saved_checks_reused": 3' in capsys.readouterr().out
