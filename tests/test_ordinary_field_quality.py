"""Bounded unchanged-field validation, not an optimizer or anatomy simulation."""

from pathlib import Path

import numpy as np
import pytest
from test_reference_ordinary_field import ordinary
from test_shape_descriptor import cube

from diffeoforge import ordinary_field_quality as quality
from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.regional_fit import _save


def setup_field(tmp_path, monkeypatch, error):
    from diffeoforge import regional_evaluation, source_refinement

    run = tmp_path / "native"
    data, _, _ = ordinary(run)
    v, f = cube()
    source, target = run / "input/source.vtk", run / "input/one.vtk"
    _save(source, v, f)
    _save(target, np.asarray(v) + [0.1, 0, 0], f)
    config = data.run_report.manifest["effective_config"]
    config["model"].update(object_id="surface")
    config["model"]["attachment"]["kernel_width"] = 0.4
    config["model"]["deformation"].update(use_rk2=True, timepoints=37)
    data.run_report.manifest["inputs"] = [
        dict(
            role="template",
            staged_path="input/source.vtk",
            geometry={"sha256": sha256_file(source)},
        ),
        dict(role="subject", staged_path="input/one.vtk", geometry={"sha256": sha256_file(target)}),
    ]
    calls = []

    def values(points, count):
        result = np.asarray(points, float).copy()
        result[:, 0] += 0.1 + error(count) * (result[:, 0] > 0)
        return result

    native = run / "output/D__Reconstruction__surface__subject_one.vtk.vtk"
    _save(native, values(v, 37), f)
    data.run_report.inventory.append(
        dict(path=native.name, sha256=sha256_file(native), bytes=native.stat().st_size)
    )
    bindings = {p: sha256_file(p) for p in run.rglob("*") if p.is_file()}
    read_calls = []
    monkeypatch.setattr(
        regional_evaluation, "field_inputs", lambda *a: read_calls.append(1) or data
    )

    def evaluate(run, destination, *, count, _source, **kwargs):
        calls.append(count)
        directory = Path(destination)
        directory.mkdir()
        mesh = read_vtk_polydata(_source)
        endpoint = directory / "endpoint.vtk"
        _save(endpoint, values(mesh.vertices, count), mesh.triangles)
        return dict(
            timepoints=count,
            endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)),
            reference_source=dict(path=str(_source), sha256=sha256_file(_source)),
            prefix=None,
            source_run=str(run),
            optimizer_updates=0,
            anatomical_approval=False,
        )

    def refine(run, receipt, destination, plan, **kwargs):
        assert receipt["whole_surface_sampling"] is True
        return dict(receipt, source_refinement=dict(resource_limit=False))

    monkeypatch.setattr(regional_evaluation, "evaluate", evaluate)
    monkeypatch.setattr(source_refinement, "refine_evaluation", refine)
    monkeypatch.setattr(
        quality,
        "_surface",
        lambda p: dict(intersecting_faces=0, nonpositive_faces=0, vertices=len(v), faces=len(f)),
    )
    return run, calls, read_calls, bindings


def test_finer_577_grid_resolves_same_field_without_larger_fit_or_threshold(tmp_path, monkeypatch):
    run, calls, read_calls, bindings = setup_field(tmp_path, monkeypatch, lambda n: 30 / n**2)
    result = quality.qualify(run, tmp_path / "quality")
    assert result["passed"] and result["temporal_grid_stable"]
    assert result["temporal_grid_checks"][-1]["fine"] == 577
    assert max(calls) == 577
    assert result["policy"]["temporal_maximum_relative"] == 1e-4
    assert result["optimizer_grid_accuracy"]["passed"]
    assert result["native_export_reproduction"]["passed"]
    assert result["optimizer_updates"] == 0 and not result["anatomical_approval"]
    assert len(read_calls) == 2
    assert all(sha256_file(p) == digest for p, digest in bindings.items())


def test_unresolved_field_stops_at_declared_grid_and_stays_unapproved(tmp_path, monkeypatch):
    run, calls, _, bindings = setup_field(tmp_path, monkeypatch, lambda n: 100 / n**2)
    result = quality.qualify(run, tmp_path / "quality")
    assert not result["passed"] and not result["temporal_grid_stable"]
    assert not result["numerical_selection_suitable"] and max(calls) == 577
    assert result["optimizer_updates"] == 0
    assert all(sha256_file(p) == digest for p, digest in bindings.items())


def test_stable_dense_evaluation_does_not_hide_inaccurate_optimizer_grid(tmp_path, monkeypatch):
    run, calls, _, _ = setup_field(tmp_path, monkeypatch, lambda n: 0.25 if n == 37 else 0)
    result = quality.qualify(run, tmp_path / "quality")
    assert result["temporal_grid_stable"] and max(calls) == 145
    assert not result["optimizer_grid_accuracy"]["passed"]
    assert not result["passed"] and not result["anatomical_approval"]


def test_export_mismatch_stops_before_further_field_grids(tmp_path, monkeypatch):
    run, calls, _, _ = setup_field(tmp_path, monkeypatch, lambda n: 0)
    native = next((run / "output").glob("*Reconstruction*"))
    mesh = read_vtk_polydata(native)
    _save(native, np.asarray(mesh.vertices) + [1, 0, 0], mesh.triangles)
    from diffeoforge import regional_evaluation

    data = regional_evaluation.field_inputs(run, {})
    data.run_report.inventory[-1]["sha256"] = sha256_file(native)
    with pytest.raises(ValueError, match="Native export reproduction failed"):
        quality.qualify(run, tmp_path / "quality")
    assert calls == [37]
    assert (tmp_path / "quality/native-reproduction-failure.json").is_file()


def test_cancellation_keeps_native_fit_and_launches_no_evaluation(tmp_path, monkeypatch):
    run, calls, _, bindings = setup_field(tmp_path, monkeypatch, lambda n: 0)
    with pytest.raises(InterruptedError, match="native fit retained"):
        quality.qualify(run, tmp_path / "quality", cancelled=lambda: True)
    assert not calls and not (tmp_path / "quality").exists()
    assert all(sha256_file(p) == digest for p, digest in bindings.items())


def test_whole_surface_sampling_includes_unmarked_long_faces(tmp_path, monkeypatch):
    from diffeoforge import mesh_filter_worker, source_refinement

    v, f = cube()
    monkeypatch.setattr(mesh_filter_worker, "run_mesh_filter", lambda *a, **k: {"faces": []})
    assert not source_refinement.selection(v, f, [], 0.2).any()
    assert source_refinement.selection(v, f, [], 0.2, whole_surface=True).all()


def test_changed_native_bytes_cannot_receive_new_quality_binding(tmp_path, monkeypatch):
    run, calls, _, _ = setup_field(tmp_path, monkeypatch, lambda n: 0)
    native = next((run / "output").glob("*Reconstruction*"))
    native.write_bytes(native.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Qualification input or native reconstruction changed"):
        quality.qualify(run, tmp_path / "quality")
    assert not calls


def test_target_changed_during_checks_cannot_receive_new_quality_binding(tmp_path, monkeypatch):
    from diffeoforge import regional_evaluation

    run, _, _, _ = setup_field(tmp_path, monkeypatch, lambda n: 0)
    original = regional_evaluation.evaluate

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs["count"] == 73:
            path = run / "input/one.vtk"
            path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(regional_evaluation, "evaluate", change)
    with pytest.raises(ValueError, match="Qualification input or native reconstruction changed"):
        quality.qualify(run, tmp_path / "quality")


def test_changed_generated_endpoint_cannot_receive_quality_record(tmp_path, monkeypatch):
    run, _, _, bindings = setup_field(tmp_path, monkeypatch, lambda n: 0)
    original = quality._surface
    destination = tmp_path / "quality"
    endpoint = destination / "grid73" / "endpoint.vtk"

    def inspect(path):
        if path == endpoint:
            mesh = read_vtk_polydata(path)
            _save(path, np.asarray(mesh.vertices) + [1e-5, 0, 0], mesh.triangles)
        return original(path)

    monkeypatch.setattr(quality, "_surface", inspect)
    with pytest.raises(ValueError, match="Qualification endpoint or reference source changed"):
        quality.qualify(run, destination)
    assert not (destination / "quality.json").exists()
    assert all(sha256_file(p) == digest for p, digest in bindings.items())


def test_changed_refined_reference_cannot_receive_quality_record(tmp_path, monkeypatch):
    from diffeoforge import regional_evaluation, source_refinement

    run, _, _, bindings = setup_field(tmp_path, monkeypatch, lambda n: 0)
    destination = tmp_path / "quality"
    evaluate = regional_evaluation.evaluate

    def refine(run, receipt, directory, plan, **kwargs):
        mesh = read_vtk_polydata(Path(receipt["reference_source"]["path"]))
        directory.mkdir()
        grid = directory / "original-source-grid.vtk"
        _save(grid, mesh.vertices, mesh.triangles)
        grid.write_bytes(grid.read_bytes() + b"\n")
        return dict(receipt, reference_source=dict(path=str(grid), sha256=sha256_file(grid)))

    def change(*args, **kwargs):
        if Path(args[1]).name == "optimizer-on-final-source":
            grid = kwargs["_source"]
            grid.write_bytes(grid.read_bytes() + b"\n")
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(source_refinement, "refine_evaluation", refine)
    monkeypatch.setattr(regional_evaluation, "evaluate", change)
    with pytest.raises(ValueError, match="Qualification endpoint or reference source changed"):
        quality.qualify(run, destination)
    assert not (destination / "quality.json").exists()
    assert all(sha256_file(p) == digest for p, digest in bindings.items())


def test_cancellation_during_final_field_verification_is_honored(tmp_path, monkeypatch):
    from diffeoforge import regional_evaluation

    run, _, _, _ = setup_field(tmp_path, monkeypatch, lambda n: 0)
    destination = tmp_path / "quality"
    field_inputs = regional_evaluation.field_inputs
    calls = 0

    def verify(*args, **kwargs):
        nonlocal calls
        calls += 1
        return field_inputs(*args, **kwargs)

    monkeypatch.setattr(regional_evaluation, "field_inputs", verify)
    with pytest.raises(InterruptedError, match="native fit retained"):
        quality.qualify(run, destination, cancelled=lambda: calls >= 2)
    assert not (destination / "quality.json").exists()
