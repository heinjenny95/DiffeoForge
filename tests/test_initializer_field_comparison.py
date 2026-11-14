from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def comparison():
    path = Path(__file__).parents[1] / "tools/compare_initializer_fields.py"
    spec = importlib.util.spec_from_file_location("initializer_fields", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet(root, protocol, **updates):
    root.mkdir()
    arrays = {
        "template": np.arange(24, dtype=np.float64).reshape(8, 3),
        "controls": np.arange(12, dtype=np.float64).reshape(4, 3),
        "momenta": np.arange(36, dtype=np.float64).reshape(3, 4, 3) / 100,
    }
    record = {
        "protocol": protocol,
        "subjects": [{"id": f"form-{i}", "sha256": str(i) * 64} for i in range(3)],
        "basis_identity": {"template_sha256": "a" * 64, "controls_sha256": "b" * 64},
        "settings": {
            "max_iterations": 20,
            "convergence_tolerance": 1e-6,
            "timepoints": 10,
            "precision": "float32",
            "freeze_template": True,
            "freeze_control_points": True,
            "integrator": "rk2",
        },
        "pilot_indices": [1],
        "completed": [
            {"index": 0, "iterations": 20, "stop": "iteration_limit"},
            {"index": 2, "iterations": 8, "stop": "native_tolerance"},
        ],
        "wall_seconds": 100,
        "arrays": {},
    }
    for name, array in arrays.items():
        np.save(root / (name + ".npy"), array)
        record["arrays"][name] = {
            "path": name + ".npy",
            "sha256": hashlib.sha256((root / (name + ".npy")).read_bytes()).hexdigest(),
        }
    record.update(updates)
    path = root / "packet.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def update_record(path, edit):
    record = json.loads(path.read_text())
    edit(record)
    path.write_text(json.dumps(record), encoding="utf-8")


def update_array(path, name, edit):
    target = path.parent / (name + ".npy")
    values = np.load(target)
    replacement = edit(values)
    np.save(target, values if replacement is None else replacement)
    update_record(
        path,
        lambda record: record["arrays"][name].update(
            sha256=hashlib.sha256(target.read_bytes()).hexdigest()
        ),
    )


def test_reordered_worker_completion_keeps_every_field_and_reports_capped_status(
    tmp_path, comparison
):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL, wall_seconds=40)
    update_record(right, lambda record: record["completed"].reverse())
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()
    }
    result = comparison.compare(left, right)
    assert result["passed"]
    assert result["capped_subjects"] == 1
    assert result["observed_wall_time_ratio"] == 2.5
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in before.items())


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r["completed"].pop(),
        lambda r: r["completed"].append(dict(r["completed"][0])),
        lambda r: r["completed"][0].update(index=1),
        lambda r: r["completed"][0].update(iterations=19),
        lambda r: r["completed"][0].update(stop="unknown"),
        lambda r: r["completed"][0].update(stop="line_search_exhausted"),
        lambda r: r["subjects"].__setitem__(2, dict(r["subjects"][0])),
        lambda r: r["settings"].update(freeze_template=False),
        lambda r: r["settings"].pop("precision"),
        lambda r: r.update(wall_seconds=float("nan")),
    ],
)
def test_incomplete_or_invalid_evidence_cannot_qualify(tmp_path, comparison, edit):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    update_record(right, edit)
    with pytest.raises(ValueError):
        comparison.compare(left, right)


@pytest.mark.parametrize(
    "edit,check",
    [
        (lambda r: r["subjects"].reverse(), "ordered_subjects_identical"),
        (
            lambda r: r["basis_identity"].update(template_sha256="c" * 64),
            "original_basis_identities_identical",
        ),
        (lambda r: r["settings"].update(convergence_tolerance=1e-5), "recorded_settings_identical"),
        (lambda r: r["completed"][1].update(iterations=9), "native_stops_and_iterations_identical"),
    ],
)
def test_comparable_fields_do_not_hide_changed_contracts(tmp_path, comparison, edit, check):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    update_record(right, edit)
    result = comparison.compare(left, right)
    assert not result["passed"] and not result["checks"][check]
    assert result["observed_wall_time_ratio"] is None


@pytest.mark.parametrize(
    "name,edit",
    [
        ("momenta", lambda a: a.__setitem__((1, 0, 0), a[1, 0, 0] + 1e-12)),
        ("momenta", lambda a: a.__setitem__((0, 0, 0), -0.0)),
        ("controls", lambda a: a[::-1].copy()),
        ("template", lambda a: a.__setitem__((0, 0), 0.001)),
        ("momenta", lambda a: a.astype(np.float32)),
    ],
)
def test_any_retained_field_or_basis_bit_change_blocks_equality(tmp_path, comparison, name, edit):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    update_array(right, name, edit)
    result = comparison.compare(left, right)
    assert not result["passed"] and not result["checks"][name + "_identical"]


def test_rejects_nonfinite_tampered_or_external_arrays(tmp_path, comparison):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    update_array(right, "momenta", lambda a: a.__setitem__((0, 0, 0), np.inf))
    with pytest.raises(ValueError, match="finite"):
        comparison.compare(left, right)
    update_array(right, "momenta", lambda a: a.__setitem__((0, 0, 0), 0))
    with (right.parent / "momenta.npy").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        comparison.compare(left, right)
    update_record(right, lambda r: r["arrays"]["momenta"].update(path="../left/momenta.npy"))
    with pytest.raises(ValueError, match="within"):
        comparison.compare(left, right)


def test_cli_preserves_existing_proof(tmp_path, comparison):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    proof = tmp_path / "proof.json"
    arguments = [str(left), str(right), "--output", str(proof)]
    assert comparison.main(arguments) == 0
    before = proof.read_bytes()
    with pytest.raises(FileExistsError):
        comparison.main(arguments)
    assert proof.read_bytes() == before


def test_explicitly_empty_pilot_set_requires_every_subject_to_complete(tmp_path, comparison):
    left = packet(tmp_path / "left", comparison.PROTOCOL)
    right = packet(tmp_path / "right", comparison.PROTOCOL)
    for path in (left, right):
        update_record(path, lambda r: r.update(pilot_indices=[]))
        update_record(
            path,
            lambda r: r["completed"].append(
                {"index": 1, "iterations": 5, "stop": "native_tolerance"}
            ),
        )
    assert comparison.compare(left, right)["passed"]
    update_record(right, lambda r: r.pop("pilot_indices"))
    with pytest.raises(ValueError, match="pilot"):
        comparison.compare(left, right)
