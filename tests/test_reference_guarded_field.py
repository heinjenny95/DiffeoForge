"""Synthetic exact-CP selection; no optimizer/native shooting or owner data."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge.mesh import sha256_file
from diffeoforge.reference_finite_accepted_guard import DECLARATION
from diffeoforge.reference_guarded_field import bind_original_control_points
from diffeoforge.reference_pca import ReferenceMomentaInput
from diffeoforge.reference_pca_deformations import _write_momenta


def record(root, path):
    return dict(
        path=path.relative_to(root).as_posix(), bytes=path.stat().st_size, sha256=sha256_file(path)
    )


def fixture(root):
    root.mkdir(exist_ok=True)
    cp = root / "input/control-points/original.txt"
    cp.parent.mkdir(parents=True)
    controls = np.array(
        [
            [0.123456789012345, -0.234567890123456, 0.3],
            [1.234567890123456, 2.345678901234567, -3.456789012345678],
        ]
    )
    np.savetxt(cp, controls, fmt="%.17g")
    output = root / "output"
    output.mkdir()
    exported = output / "Controls.txt"
    np.savetxt(exported, controls, fmt="%.6f")
    m = np.arange(6, dtype=np.float64).reshape(1, 2, 3) / 10
    mp = output / "Momenta.txt"
    _write_momenta(mp, m)
    engine = root / "engine"
    engine.mkdir()
    model = engine / "model.xml"
    model.write_text(
        "<model><initial-control-points>../input/control-points/original.txt</initial-control-points></model>"
    )
    guard = output / "numerical-guard"
    guard.mkdir()
    session = guard / "session.json"
    session.write_text(
        json.dumps(
            {
                "provenance": {
                    "scope": DECLARATION,
                    "actual_control_basis": {
                        "basis": "staged_control_points",
                        "shape": [2, 3],
                        "dtype": controls.dtype.str,
                        "sha256": hashlib.sha256(controls.tobytes()).hexdigest(),
                    },
                }
            }
        )
    )
    vector = m.ravel()
    key = hashlib.sha256(
        str(vector.shape).encode() + vector.dtype.str.encode() + vector.tobytes()
    ).hexdigest()
    events = guard / "events.jsonl"
    events.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {
                    "kind": "objective_evaluation",
                    "parameter_sha256": key,
                    "evaluation_id": 1,
                    "objective_finite": True,
                    "gradient_finite": True,
                },
                {
                    "kind": "initial_accepted",
                    "parameter_sha256": key,
                    "evaluation_reference": 1,
                    "gradient_finite": True,
                },
                {
                    "kind": "native_export_parameter_binding",
                    "parameter_sha256": key,
                    "evaluation_reference": 1,
                    "internal_callback": False,
                },
            ]
        )
        + "\n"
    )
    config = {
        "project": {
            "parameter_provenance": {
                "finite_accepted_guard": DECLARATION,
                "regional_fit": {"version": "regional-fit-v1"},
            }
        },
        "optimization": {"method": "lbfgs", "freeze_template": True, "freeze_control_points": True},
    }
    report = SimpleNamespace(
        manifest={
            "effective_config": config,
            "inputs": [],
            "protected_artifacts": [record(root, cp), record(root, model)],
        },
        inventory=[record(output, p) for p in (session, events, mp, exported)],
        result={"status": "completed"},
    )
    for name in (
        "manifest.json",
        "result.json",
        "output-inventory.json",
        "engine/optimization_parameters.xml",
    ):
        (root / name).write_text("{}")
    data = ReferenceMomentaInput(
        run_directory=root,
        run_report=report,
        momenta_path=mp,
        control_points_path=exported,
        momenta_record=record(output, mp),
        control_points_record=record(output, exported),
        subject_labels=("one.vtk",),
        momenta=m,
        control_points=np.loadtxt(exported),
        source_hashes={},
    )
    return data, controls, cp


def test_original_cp_replaces_rounded_export_only_in_new_guarded_regional_input(tmp_path):
    data, original, path = fixture(tmp_path)
    assert not np.array_equal(original.view(np.uint64), data.control_points.view(np.uint64))
    bound = bind_original_control_points(data)
    assert bound.control_points_path == path
    assert bound.control_points_record["namespace"] == "run"
    assert bound.control_points_record["basis"] == "original_frozen_input"
    assert np.array_equal(bound.control_points.view(np.uint64), original.view(np.uint64))
    assert np.array_equal(bound.momenta.view(np.uint64), data.momenta.view(np.uint64))
    assert not bound.control_points.flags.writeable
    assert data.control_points_path.name == "Controls.txt"


def test_historical_fields_return_by_identity_without_reading_guard_metadata(tmp_path):
    data, _, _ = fixture(tmp_path)
    data.run_report.manifest["effective_config"]["project"]["parameter_provenance"].pop(
        "finite_accepted_guard"
    )
    (tmp_path / "output/numerical-guard/session.json").unlink()
    assert bind_original_control_points(data) is data


@pytest.mark.parametrize(
    "change", ["original_cp", "xml", "session", "events", "momenta", "violation"]
)
def test_changed_or_unbound_inputs_and_guard_evidence_fail_closed(tmp_path, change):
    data, _, cp = fixture(tmp_path)
    if change == "momenta":
        data = replace(data, momenta=data.momenta + 1)
    elif change == "violation":
        (tmp_path / "output/numerical-guard/violation.json").write_text("{}")
    else:
        path = {
            "original_cp": cp,
            "xml": tmp_path / "engine/model.xml",
            "session": tmp_path / "output/numerical-guard/session.json",
            "events": tmp_path / "output/numerical-guard/events.jsonl",
        }[change]
        with path.open("a") as f:
            f.write(" ")
    with pytest.raises(ValueError):
        bind_original_control_points(data)


def test_cache_keeps_exact_input_basis_and_rechecks_guard_binding_metadata(tmp_path, monkeypatch):
    import diffeoforge.reference_pca as pca
    from diffeoforge.regional_evaluation import field_inputs

    data, original, path = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(pca, "load_reference_momenta", lambda *a, **k: calls.append(1) or data)
    cache = {}
    first = field_inputs(tmp_path, cache)
    second = field_inputs(tmp_path, cache)
    assert first is second and len(calls) == 1
    assert first.control_points_path == path
    assert np.array_equal(first.control_points.view(np.uint64), original.view(np.uint64))
    with (tmp_path / "output/numerical-guard/events.jsonl").open("a") as f:
        f.write(" ")
    with pytest.raises(ValueError, match="cached fixed field"):
        field_inputs(tmp_path, cache)


@pytest.mark.parametrize("change", ["not_finite", "different_evaluation"])
def test_export_must_reference_the_same_finite_accepted_evaluation(tmp_path, change):
    data, _, _ = fixture(tmp_path)
    path = tmp_path / "output/numerical-guard/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "not_finite":
        events[0]["objective_finite"] = False
    else:
        events[-1]["evaluation_reference"] = 2
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    for row in data.run_report.inventory:
        if row["path"] == "numerical-guard/events.jsonl":
            row.update(record(tmp_path / "output", path))
    with pytest.raises(ValueError, match="matching finite accepted FG record"):
        bind_original_control_points(data)
