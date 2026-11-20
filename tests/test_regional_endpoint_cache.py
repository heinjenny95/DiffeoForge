"""Operation-local endpoint reuse preserves exact files and qualification identity."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from diffeoforge import (
    reference_fixed_shooting,
    reference_guarded_field,
    reference_pca,
    regional_fit,
)
from diffeoforge import regional_evaluation as evaluation
from diffeoforge.mesh import read_vtk_points, read_vtk_polydata, sha256_file


@pytest.fixture
def case(tmp_path, monkeypatch):
    runs, plans, calls, loads = {}, {}, [], []
    faces = np.array([[0, 1, 2], [0, 1, 3]], int)
    vertices = np.array([[0., 0, 0], [1., 0, 0], [0, 1., 0], [0, 0, 1.]])
    for index, name in enumerate(("parent", "child")):
        run = tmp_path / name
        (run / "engine").mkdir(parents=True)
        config = dict(project=dict(fixture_run=name), input={},
                      model=dict(object_id="surface"), optimization=dict(freeze_template=True))
        manifest = dict(effective_config=config, inputs=[dict(role="template",
                                                             staged_path="template.vtk")])
        for filename, value in (("manifest.json", manifest), ("result.json", dict(completed=True)),
                                ("output-inventory.json", {})):
            (run / filename).write_text(json.dumps(value))
        for filename in ("model.xml", "optimization_parameters.xml"):
            (run / "engine" / filename).write_text(filename)
        regional_fit._save(run / "template.vtk", vertices, faces)
        (run / "controls.txt").write_text("0 0 0\n")
        (run / "momenta.txt").write_text(str(index + 1))
        runs[name] = SimpleNamespace(path=run, control_points_path=run / "controls.txt",
            momenta_path=run / "momenta.txt", source_hashes={}, subject_labels=("target.vtk",),
            run_report=SimpleNamespace(manifest=manifest))
        plans[name] = None

    def load(run, **kwargs):
        loads.append(Path(run))
        return runs[Path(run).name]

    def shoot(config, seed_root, seed, destination, count, **options):
        calls.append((Path(seed["source_run_directory"]), count, options.get("point_cloud", False)))
        destination.mkdir(parents=True, exist_ok=False)
        source, engine = destination / "source", destination / "engine"
        source.mkdir()
        engine.mkdir()
        for role, name in (("template", "estimated-template.vtk"),
                           ("control_points", "control-points.txt"),
                           ("momenta", "endpoint-momenta.txt")):
            shutil.copyfile(seed_root / seed["files"][role]["copy"], source / name)
        for name in ("model.xml", "optimization_parameters.xml"):
            shutil.copyfile(Path(seed["source_run_directory"]) / "engine" / name, engine / name)
        protected = {str(p.relative_to(destination)): sha256_file(p)
                     for p in destination.rglob("*") if p.is_file()}
        point_cloud = options.get("point_cloud", False)
        if point_cloud:
            points, topology = np.asarray(read_vtk_points(source / "estimated-template.vtk")), None
        else:
            mesh = read_vtk_polydata(source / "estimated-template.vtk")
            points, topology = np.asarray(mesh.vertices), mesh.triangles
        delta = float((source / "endpoint-momenta.txt").read_text()) / count
        (destination / "output").mkdir()
        (destination / "endpoints").mkdir()
        native = destination / "output/Shooting__endpoint.vtk"
        endpoint = destination / "endpoints/Shooting__endpoint.vtk"
        regional_fit._save(native, points + delta, topology)
        shutil.copyfile(native, endpoint)
        (destination / "output/Shooting__grid.json").write_text(json.dumps(dict(timepoints=count)))
        (destination / "stdout.log").write_text("synthetic fixed Shooting receipt; no process\n")
        return {"target.vtk": endpoint}, protected

    monkeypatch.setattr(reference_pca, "load_reference_momenta", load)
    monkeypatch.setattr(reference_guarded_field, "bind_original_control_points", lambda x: x)
    monkeypatch.setattr(regional_fit, "read_plan", lambda cfg: plans[cfg["project"]["fixture_run"]])
    monkeypatch.setattr(reference_fixed_shooting, "shoot", shoot)
    return SimpleNamespace(root=tmp_path, runs=runs, plans=plans, calls=calls, loads=loads,
                           vertices=vertices, faces=faces)


def test_repeated_surface_evaluation_reuses_bytes_at_new_requested_paths(case):
    cache = {}
    run = case.runs["parent"].path
    first = evaluation.evaluate(run, case.root / "first", _cache=cache)
    first["protected"][str(Path("source/control-points.txt"))] = "caller mutation"
    second = evaluation.evaluate(run, case.root / "second", _cache=cache)
    uncached = evaluation.evaluate(run, case.root / "uncached")
    assert len(case.calls) == 2 and len(case.loads) == 2
    assert second["endpoint"]["path"] == str(case.root / "second/endpoints/Shooting__endpoint.vtk")
    assert first["endpoint"]["sha256"] == second["endpoint"]["sha256"] == (
        uncached["endpoint"]["sha256"])
    assert second["protected"] == uncached["protected"]
    for relative, digest in second["protected"].items():
        assert sha256_file(case.root / "second" / relative) == digest
    assert second["native_endpoint_reuse"]["native_process_started"] is False
    assert json.loads((case.root / "second/evaluation.json").read_text()) == second
    assert "native_endpoint_reuse" not in first and "native_endpoint_reuse" not in uncached


def test_every_residual_prefix_is_reused_and_reverified_with_fresh_receipts(case):
    parent, child = (case.runs[name].path for name in ("parent", "child"))
    case.plans["child"] = dict(residual=dict(parent_run=str(parent),
        parent_manifest_sha256=sha256_file(parent / "manifest.json")))
    cache = {}
    first = evaluation.evaluate(child, case.root / "first", _cache=cache)
    first["prefix"]["endpoint"]["sha256"] = "caller mutation"
    second = evaluation.evaluate(child, case.root / "second", _cache=cache)
    assert len(case.calls) == 2 and set(case.loads) == {parent, child}
    assert second["prefix"]["endpoint"]["path"].startswith(str(case.root / "second-prefix"))
    assert second["prefix"]["native_endpoint_reuse"]["native_process_started"] is False
    assert second["native_endpoint_reuse"]["native_process_started"] is False
    (parent / "momenta.txt").write_text("changed parent coefficients")
    with pytest.raises(ValueError, match="cached fixed field"):
        evaluation.evaluate(child, case.root / "third", _cache=cache)
    assert len(case.calls) == 2 and not (case.root / "third").exists()


@pytest.mark.parametrize("mutation", ["endpoint", "protected", "missing"])
def test_changed_cached_native_artifacts_fail_closed_without_a_new_process(case, mutation):
    run, cache = case.runs["parent"].path, {}
    receipt = evaluation.evaluate(run, case.root / "first", _cache=cache)
    path = (Path(receipt["endpoint"]["path"]) if mutation != "protected" else
            case.root / "first/source/control-points.txt")
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed cached artifact")
    with pytest.raises(ValueError, match="cached fixed Shooting artifact"):
        evaluation.evaluate(run, case.root / "second", _cache=cache)
    assert len(case.calls) == 1 and not (case.root / "second").exists()


@pytest.mark.parametrize("asset", ["momenta.txt", "controls.txt", "engine/model.xml",
                                    "template.vtk", "result.json"])
def test_changed_field_inputs_cannot_hit_or_launch_from_a_stale_binding(case, asset):
    run, cache = case.runs["parent"].path, {}
    evaluation.evaluate(run, case.root / "first", _cache=cache)
    (run / asset).write_bytes(b"changed input")
    with pytest.raises(ValueError, match="cached fixed field"):
        evaluation.evaluate(run, case.root / "second", _cache=cache)
    assert len(case.calls) == 1


def test_new_grid_time_count_and_point_mode_have_separate_keys(case):
    run, cache = case.runs["parent"].path, {}
    original = evaluation.evaluate(run, case.root / "surface73", _cache=cache)
    evaluation.evaluate(run, case.root / "surface145", count=145, _cache=cache)
    alternate = case.root / "alternate.vtk"
    regional_fit._save(alternate, case.vertices * 2, case.faces)
    evaluation.evaluate(run, case.root / "alternate", _source=alternate, _cache=cache)
    points = evaluation.evaluate_points(run, case.vertices, case.root / "points", count=73,
                                        _cache=cache)
    repeated = evaluation.evaluate_points(run, case.vertices, case.root / "points-again", count=73,
                                          _cache=cache)
    assert len(case.calls) == 4
    assert original["endpoint"]["sha256"] != points["endpoint"]["sha256"]
    assert repeated["endpoint"]["sha256"] == points["endpoint"]["sha256"]
    assert repeated["endpoint"]["path"].startswith(str(case.root / "points-again"))
    assert repeated["native_endpoint_reuse"]["native_process_started"] is False
    regional_fit._save(alternate, case.vertices * 3, case.faces)
    evaluation.evaluate(run, case.root / "alternate-new", _source=alternate, _cache=cache)
    assert len(case.calls) == 5


def test_cancel_and_existing_destination_never_replay_or_overwrite(case):
    run, cache = case.runs["parent"].path, {}
    first = evaluation.evaluate(run, case.root / "first", _cache=cache)
    with pytest.raises(InterruptedError, match="cancelled"):
        evaluation.evaluate(run, case.root / "cancelled", _cache=cache, cancelled=lambda: True)
    assert not (case.root / "cancelled").exists()
    with pytest.raises(FileExistsError):
        evaluation.evaluate(run, case.root / "first", _cache=cache)
    assert len(case.calls) == 1
    assert sha256_file(Path(first["endpoint"]["path"])) == first["endpoint"]["sha256"]


def test_current_field_is_rechecked_after_a_longer_prefix_replay(case, monkeypatch):
    parent, child = (case.runs[name].path for name in ("parent", "child"))
    case.plans["child"] = dict(residual=dict(parent_run=str(parent),
        parent_manifest_sha256=sha256_file(parent / "manifest.json")))
    shoot = reference_fixed_shooting.shoot

    def altered(*args, **kwargs):
        result = shoot(*args, **kwargs)
        if Path(args[2]["source_run_directory"]) == parent:
            (child / "controls.txt").write_text("changed during prefix replay")
        return result

    monkeypatch.setattr(reference_fixed_shooting, "shoot", altered)
    with pytest.raises(ValueError, match="cached fixed field"):
        evaluation.evaluate(child, case.root / "check", _cache={})
    assert len(case.calls) == 1 and case.calls[0][0] == parent
    assert not (case.root / "check").exists()


def test_a_different_native_scope_with_run_metadata_is_not_cached_as_fixed_shooting(
    case, monkeypatch,
):
    shoot = reference_fixed_shooting.shoot

    def other_scope(*args, **kwargs):
        result = shoot(*args, **kwargs)
        (args[3] / "result.json").write_text('{"run_id":"different-lifecycle"}')
        return result

    monkeypatch.setattr(reference_fixed_shooting, "shoot", other_scope)
    cache = {}
    with pytest.raises(ValueError, match="Unexpected fixed Shooting artifact"):
        evaluation.evaluate(case.runs["parent"].path, case.root / "check", _cache=cache)
    assert not any(isinstance(key, tuple) for key in cache)


def test_endpoint_memo_is_local_to_the_explicit_operation_cache(case):
    run = case.runs["parent"].path
    evaluation.evaluate(run, case.root / "first", _cache={})
    evaluation.evaluate(run, case.root / "second", _cache={})
    assert len(case.calls) == 2


def test_windows_protected_path_spelling_is_preserved_across_reuse(case, monkeypatch):
    shoot = reference_fixed_shooting.shoot

    def windows_keys(*args, **kwargs):
        paths, protected = shoot(*args, **kwargs)
        return paths, {name.replace("/", "\\"): digest for name, digest in protected.items()}

    monkeypatch.setattr(reference_fixed_shooting, "shoot", windows_keys)
    cache = {}
    first = evaluation.evaluate(case.runs["parent"].path, case.root / "first", _cache=cache)
    second = evaluation.evaluate(case.runs["parent"].path, case.root / "second", _cache=cache)
    assert second["protected"] == first["protected"]
    assert all("\\" in name for name in second["protected"])
    for name, digest in second["protected"].items():
        assert sha256_file(case.root / "second" / Path(name.replace("\\", "/"))) == digest
    assert len(case.calls) == 1
