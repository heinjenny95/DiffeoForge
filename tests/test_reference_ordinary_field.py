"""Ordinary singleton fields retain the exact accepted original basis."""

import json
from dataclasses import replace

import numpy as np
import pytest
from test_reference_guarded_field import fixture, record

from diffeoforge.reference_guarded_field import bind_original_control_points
from diffeoforge.reference_ordinary_guard import DECLARATION


def ordinary(root):
    data, controls, path = fixture(root)
    config = data.run_report.manifest["effective_config"]
    p = config["project"]["parameter_provenance"]
    p.pop("regional_fit")
    p.update(
        finite_accepted_guard=dict(DECLARATION),
        recommendation={"calibration_plan": {"execution_scope": "single_specimen_probe"}},
    )
    config.update(
        model={
            "attachment": {"type": "varifold"},
            "deformation": {"initial_control_points": str(path)},
        },
        runtime={"precision": "float32"},
    )
    session = root / "output/numerical-guard/session.json"
    value = json.loads(session.read_text())
    value["provenance"]["scope"] = dict(DECLARATION)
    session.write_text(json.dumps(value))
    row = next(r for r in data.run_report.inventory if r["path"].endswith("session.json"))
    row.update(record(root / "output", session))
    return data, controls, path


def test_completed_ordinary_field_uses_original_control_bits_and_same_accepted_momenta(tmp_path):
    data, controls, path = ordinary(tmp_path)
    bound = bind_original_control_points(data)
    assert bound.control_points_path == path
    assert np.array_equal(bound.control_points.view(np.uint64), controls.view(np.uint64))
    assert np.array_equal(bound.momenta.view(np.uint64), data.momenta.view(np.uint64))
    assert not bound.control_points.flags.writeable


def test_guided_initializer_uses_the_same_verified_original_ordinary_basis(tmp_path, monkeypatch):
    from diffeoforge import guided_refinement, reference_pca

    data, controls, path = ordinary(tmp_path)
    monkeypatch.setattr(reference_pca, "load_reference_momenta", lambda *a, **k: data)
    bound = guided_refinement.load_field(tmp_path)
    assert bound.control_points_path == path
    assert np.array_equal(bound.control_points.view(np.uint64), controls.view(np.uint64))


@pytest.mark.parametrize(
    "change",
    ["regional", "float64", "joint", "free", "momenta", "cp", "session", "events", "violation"],
)
def test_ordinary_field_rejects_wrong_scope_changed_basis_and_unbound_export(tmp_path, change):
    data, _, cp = ordinary(tmp_path)
    config = data.run_report.manifest["effective_config"]
    if change == "regional":
        config["project"]["parameter_provenance"]["regional_fit"] = {}
    elif change == "float64":
        config["runtime"]["precision"] = "float64"
    elif change == "joint":
        data = replace(data, subject_labels=("one.vtk", "two.vtk"))
    elif change == "free":
        config["optimization"]["freeze_template"] = False
    elif change == "momenta":
        data = replace(data, momenta=data.momenta + 0.01)
    elif change == "violation":
        (tmp_path / "output/numerical-guard/violation.json").write_text("{}")
    else:
        path = (
            cp
            if change == "cp"
            else tmp_path
            / (
                "output/numerical-guard/"
                + ("session.json" if change == "session" else "events.jsonl")
            )
        )
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        bind_original_control_points(data)
