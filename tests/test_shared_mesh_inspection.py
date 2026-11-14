"""Cross-project persistence, partial invalidation and exact alignment reuse."""

import json
import shutil

import pytest
from test_preprocessing import MESH_DIRECTORY, _write_landmarks

from diffeoforge import input_preflight as inputs
from diffeoforge import mesh_inspection_cache as cache
from diffeoforge import preprocessing
from diffeoforge.mesh import sha256_file
from diffeoforge.project_checkpoint import CheckpointUnavailable, checkpoint_directory


def cohort(tmp_path):
    source = tmp_path / "meshes"
    source.mkdir()
    for path in MESH_DIRECTORY.glob("*.vtk"):
        shutil.copyfile(path, source / path.name)
    return tuple(sorted(source.glob("*.vtk")))


def forbidden(*_a, **_kw):
    pytest.fail("A compatible saved check must not parse or inspect geometry")


def test_new_project_and_copied_names_reuse_content_checks(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    shared = tmp_path / "shared"
    first = inputs.inspect_mesh_input_cohort(
        paths, cache_project=tmp_path / "old", shared_cache=shared
    )
    copied = tmp_path / "copied"
    copied.mkdir()
    names = []
    for i, path in enumerate(paths):
        dest = copied / f"renamed-{i}.vtk"
        shutil.copyfile(path, dest)
        names.append(dest)
    monkeypatch.setattr(inputs, "load_surface_mesh", forbidden)
    monkeypatch.setattr(inputs, "assess_normalized_triangle_mesh", forbidden)
    events = []
    second = inputs.inspect_mesh_input_cohort(
        names,
        shared_cache=shared,
        cache_project=tmp_path / "new",
        cache_only=True,
        inspection_callback=lambda *_args: events.append(_args[-1]),
    )
    assert [r.sha256 for r in first.metadata] == [r.sha256 for r in second.metadata]
    assert events.count("Reused saved mesh validation") == len(paths)
    assert all(str(copied) in r.path for r in second.metadata)


def test_previous_project_cache_migrates_without_any_new_validation(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    old = tmp_path / "old"
    first = inputs.inspect_mesh_input_cohort(paths, cache_project=old)
    monkeypatch.setattr(inputs, "load_surface_mesh", forbidden)
    second = inputs.inspect_mesh_input_cohort(
        paths,
        cache_project=tmp_path / "new",
        cache_sources=(old,),
        shared_cache=tmp_path / "shared",
        cache_only=True,
    )
    assert first == second
    assert len(list(checkpoint_directory(tmp_path / "shared").glob("surface-*.json"))) == len(paths)


def test_reuse_retains_failed_topology_evidence(tmp_path, monkeypatch):
    import numpy as np

    from diffeoforge.mesh import write_vtk_polydata

    paths = list(cohort(tmp_path))
    bad = paths[0]
    bad.unlink()
    write_vtk_polydata(bad, np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                       np.array([[0, 1, 2], [0, 1, 2]]), title="Duplicate synthetic faces")
    shared = tmp_path / "shared"
    first = inputs.inspect_mesh_input_cohort(paths, shared_cache=shared)
    assert first.blockers
    assert first.mesh_quality[0].result.duplicate_faces == 1
    monkeypatch.setattr(inputs, "load_surface_mesh", forbidden)
    reused = inputs.inspect_mesh_input_cohort(paths, shared_cache=shared, cache_only=True)
    assert reused == first and not reused.ready


def test_only_changed_file_is_inspected_and_force_rechecks_all(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    shared = tmp_path / "shared"
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared)
    lines = paths[0].read_text().splitlines(keepends=True)
    lines[1] = lines[1].swapcase()
    paths[0].write_text("".join(lines))
    calls = []
    load = inputs.load_surface_mesh
    monkeypatch.setattr(inputs, "load_surface_mesh", lambda p: (calls.append(p), load(p))[1])
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared)
    assert calls == [paths[0]]
    calls.clear()
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared, force_recheck=True)
    assert calls == list(paths)


def test_rule_change_and_corrupt_entry_cannot_pass_cache_only(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    shared = tmp_path / "shared"
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared)
    path = checkpoint_directory(shared) / (cache.key(paths[0], sha256_file(paths[0])) + ".json")
    payload = json.loads(path.read_text())
    payload["sha256"] = "0" * 64
    path.write_text(json.dumps(payload))
    with pytest.raises(CheckpointUnavailable):
        inputs.inspect_mesh_input_cohort(paths, shared_cache=shared, cache_only=True)
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared)
    monkeypatch.setattr("diffeoforge.mesh_quality.QUALITY_DEFINITIONS_VERSION", "changed")
    with pytest.raises(CheckpointUnavailable):
        inputs.inspect_mesh_input_cohort(paths, shared_cache=shared, cache_only=True)


def test_new_project_reuses_verified_alignment_without_mesh_parsing(tmp_path, monkeypatch):
    paths = cohort(tmp_path)
    landmarks = _write_landmarks(tmp_path / "landmarks.csv")
    shared, old, new = (tmp_path / p for p in ("shared", "old", "new"))
    inputs.inspect_mesh_input_cohort(paths, shared_cache=shared, cache_project=old)
    template = next(p for p in paths if p.name == "template.vtk")
    first = preprocessing.prepare_landmark_aligned_inputs(
        template.parent, project_directory=old, landmarks_file=landmarks, template=template
    )
    before = {p: sha256_file(p) for p in first.directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(preprocessing, "load_surface_mesh", forbidden)
    monkeypatch.setattr(preprocessing, "read_surface_mesh", forbidden)
    second = preprocessing.prepare_landmark_aligned_inputs(
        template.parent,
        project_directory=new,
        landmarks_file=landmarks,
        template=template,
        cache_projects=(old,),
        inspection_cache=shared,
    )
    assert first.fingerprint == second.fingerprint
    assert second.directory.is_relative_to(new)
    assert sha256_file(first.evidence) == sha256_file(second.evidence)
    assert all(sha256_file(p) == digest for p, digest in before.items())
    assert all(not p.samefile(second.directory / p.relative_to(first.directory)) for p in before)
