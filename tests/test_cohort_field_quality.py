"""Public unchanged-field fixtures; no native optimization or anatomy assertions."""

from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import cohort_field_quality as quality
from diffeoforge.mesh import read_vtk_points, sha256_file
from diffeoforge.regional_fit import _save


def field(tmp_path, monkeypatch, *, error=lambda n: 0, width=10):
    from diffeoforge import reference_fixed_shooting as shooting
    from diffeoforge import reference_pca, reference_pca_deformations

    run = tmp_path / "native"
    (run / "output").mkdir(parents=True)
    (run / "input").mkdir()
    for name in ("manifest.json", "result.json", "output-inventory.json"):
        (run / name).write_text("{}")
    source = run / "output/template.vtk"
    v, f = cube()
    _save(source, v, f)
    q, m = run / "output/q.txt", run / "output/m.txt"
    q.write_text("0 0 0\n")
    m.write_text("0 0 0\n0 0 0\n")
    config = dict(
        project=dict(parameter_provenance={}),
        model=dict(
            object_id="surface",
            deformation=dict(timepoints=37, use_rk2=True),
            attachment=dict(kernel_width=width),
        ),
    )
    labels = ["a.vtk", "b.vtk"]

    def values(points, count, index):
        result = np.asarray(points, float).copy()
        result[:, 0] += 0.1 * (index + 1) + error(count) * (result[:, 0] > 0)
        return result

    inputs, inventory = [], []
    for i, name in enumerate(labels):
        path = run / "input" / name
        _save(path, v, f)
        inputs.append(
            dict(
                role="subject", staged_path="input/" + name, geometry=dict(sha256=sha256_file(path))
            )
        )
        path = run / "output" / ("D__Reconstruction__surface__subject_" + name + ".vtk")
        _save(path, values(v, 37, i), f)
        inventory.append(dict(path=path.name, sha256=sha256_file(path)))
    report = SimpleNamespace(
        manifest=dict(effective_config=config, inputs=inputs), inventory=inventory
    )
    data = SimpleNamespace(
        subject_labels=labels, run_report=report, control_points_path=q, momenta_path=m
    )
    monkeypatch.setattr(reference_pca, "load_reference_momenta", lambda r: data)
    monkeypatch.setattr(reference_pca_deformations, "_estimated_template_record", lambda rows: {})
    monkeypatch.setattr(reference_pca_deformations, "_safe_output_path", lambda r, row: source)
    calls, hook = [], []

    def shoot(config, root, seed, destination, count, **kwargs):
        destination.mkdir()
        points = read_vtk_points(seed["files"]["template"]["copy"])
        calls.append(dict(count=count, points=np.asarray(points).copy(), options=kwargs))
        outputs = {}
        for i, name in enumerate(labels):
            path = destination / (name + ".vtk")
            _save(path, values(points, count, i))
            outputs[name] = path
        for fn in hook:
            fn(count)
        return outputs, []

    monkeypatch.setattr(shooting, "shoot", shoot)
    monkeypatch.setattr(
        quality,
        "_surface",
        lambda p: dict(
            intersecting_faces=0, nonpositive_faces=0, vertices=len(read_vtk_points(p)), faces=0
        ),
    )
    bound = {p: sha256_file(p) for p in run.rglob("*") if p.is_file()}
    return run, calls, hook, bound


def test_shared_material_grid_keeps_native_field_unchanged(tmp_path, monkeypatch):
    run, calls, _, bound = field(tmp_path, monkeypatch, width=2)
    result = quality.qualify(run, tmp_path / "quality")
    assert result["passed"] and result["vertices"] > 8
    assert result["spatial_checks"] and result["optimizer_updates"] == 0
    rows = result["subjects"]
    assert set(rows) == {"a.vtk", "b.vtk"}
    assert (
        rows["a.vtk"]["evaluation"]["reference_source"]
        == rows["b.vtk"]["evaluation"]["reference_source"]
    )
    assert all(r["passed"] and not r["anatomical_approval"] for r in rows.values())
    assert all(sha256_file(p) == digest for p, digest in bound.items())
    assert all(c["options"]["precision"] == "float64" for c in calls)


def test_temporal_failure_at_last_grid_cannot_compare_the_grid_with_itself(tmp_path, monkeypatch):
    run, calls, _, _ = field(tmp_path, monkeypatch, error=lambda n: n * 0.001)
    observed = quality.qualify(run, tmp_path / "quality")
    assert not observed["passed"]
    import json

    result = json.loads((tmp_path / "quality/quality.json").read_text())
    assert not result["passed"] and max(c["count"] for c in calls) == 577
    assert all(r["temporal_delta"]["maximum"] > 1e-4 for r in result["subjects"].values())
    assert result["temporal_checks"][-1]["coarse"] == 289
    assert result["temporal_checks"][-1]["fine"] == 577


def test_all_forms_must_pass_the_same_unchanged_temporal_tolerance(tmp_path, monkeypatch):
    run, calls, _, _ = field(tmp_path, monkeypatch, error=lambda n: 30 / n**2)
    result = quality.qualify(run, tmp_path / "quality")
    assert result["passed"] and max(c["count"] for c in calls) == 577
    assert result["policy"]["temporal_maximum_relative"] == 1e-4
    assert all(r["evaluation"]["timepoints"] == 577 for r in result["subjects"].values())


def test_one_changed_target_invalidates_shared_field_checks(tmp_path, monkeypatch):
    run, _, hook, _ = field(tmp_path, monkeypatch)
    hook.append(lambda count: (run / "input/b.vtk").write_text("changed"))
    with pytest.raises(ValueError, match="bound final joint"):
        quality.qualify(run, tmp_path / "quality")


def test_cancel_before_any_evaluation_keeps_completed_native_files(tmp_path, monkeypatch):
    run, calls, _, bound = field(tmp_path, monkeypatch)
    with pytest.raises(InterruptedError, match="native fit retained"):
        quality.qualify(run, tmp_path / "quality", cancelled=lambda: True)
    assert calls == [] and all(sha256_file(p) == digest for p, digest in bound.items())
