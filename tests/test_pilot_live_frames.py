"""Display-only requests bind native sampled points to the right prepared run."""

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pilot_live_frames import (
    FACE_BUDGET,
    FACE_BUDGETS,
    LEGACY_VERSION,
    VERSION,
    prepare,
    read_frame,
    release,
)

pytest.importorskip("vtkmodules")


def _mesh(n=4):
    x, y = np.meshgrid(np.linspace(-1, 1, n), np.linspace(-1, 1, n))
    vertices = np.column_stack((x.ravel(), y.ravel(), (.1 * (x**2 - y**2)).ravel()))
    a = (np.arange(n - 1)[:, None] * n + np.arange(n - 1)).ravel()
    faces = np.concatenate((np.column_stack((a, a + 1, a + n)),
                            np.column_stack((a + 1, a + n + 1, a + n))))
    return vertices, faces


def _run(tmp_path: Path, n=4, *, version=VERSION):
    (tmp_path / "engine").mkdir()
    (tmp_path / "input").mkdir()
    v, f = _mesh(n)
    source = tmp_path / "input/native.vtk"
    target = tmp_path / "input/target.vtk"
    write_vtk_polydata(source, v, f, title="Source")
    write_vtk_polydata(target, v + [0, 0, .125], f, title="Target")
    model = tmp_path / "engine/model.xml"
    model.write_text("""<model><template>
        <object id="other"><filename>ignored.vtk</filename></object>
        <object id="surface"><deformable-object-type>SurfaceMesh</deformable-object-type>
        <filename>../input/native.vtk</filename></object></template></model>""", encoding="utf-8")
    runtime = tmp_path / "engine/pilot_preview_runtime.py"
    from diffeoforge.pilot_preview_assets import LEGACY_SOURCE, SOURCE

    runtime.write_bytes(LEGACY_SOURCE if version == LEGACY_VERSION else SOURCE)
    protected = [dict(path=path.relative_to(tmp_path).as_posix(), sha256=sha256_file(path))
                 for path in (source, target, model, runtime)]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(
        effective_config=dict(project=dict(parameter_provenance=dict(
            pilot_live_preview={"version": version})), model=dict(object_id="surface")),
        protected_artifacts=protected,
        inputs=[dict(role="subject", staged_path="input/target.vtk")],
    )), encoding="utf-8")
    (tmp_path / "manifest.sha256").write_text(
        f"{sha256_file(manifest)}  manifest.json\n", encoding="ascii",
    )
    return v


def test_live_marks_bind_to_staged_target_and_plan(tmp_path):
    _run(tmp_path)
    manifest = tmp_path / "manifest.json"
    data = json.loads(manifest.read_bytes())
    target = sha256_file(tmp_path / "input/target.vtk")
    marks = [dict(center=[i / 2, 0., .125], purpose=purpose, source_sha256=target)
             for i, purpose in enumerate(("problem", "problem", "fixed"))]
    path = tmp_path / "input/regional/plan.json"
    path.parent.mkdir()
    path.write_text(json.dumps(dict(target_sha256=target, instruction_regions=marks,
                                    focus_regions=[marks[1]])))
    data["protected_artifacts"].append(dict(path="input/regional/plan.json",
                                             sha256=sha256_file(path)))
    data["effective_config"]["project"]["parameter_provenance"]["regional_fit"] = {
        "sha256": sha256_file(path)}
    manifest.write_text(json.dumps(data))
    (tmp_path / "manifest.sha256").write_text(f"{sha256_file(manifest)}  manifest.json\n")
    scope = prepare(tmp_path, "verified-regions").region_scope
    assert scope["active"] == ["B"] and scope["waiting"] == ["A"] and scope["fixed"] == ["C"]
    assert scope["markers"]["B"] == tuple(marks[1]["center"])
    path.write_text("{}")
    unusable = prepare(tmp_path, "stale-regions").region_scope
    assert not unusable["markers"] and "unavailable" in unusable["text"]


def _write_frame(binding, points, *, iteration=6, identifier=None, controls=None, compressed=False):
    store = np.savez_compressed if compressed else np.savez
    frame_id = np.asarray(identifier or binding.identifier, dtype="U32")
    metadata = {} if binding.legacy_runtime else dict(
        version=np.asarray(binding.protocol_version, dtype="U32"),
        face_budget=np.asarray(binding.face_budget, dtype=np.int64))
    store(binding.folder / "frame.npz", id=frame_id, **metadata,
          iteration=np.asarray(iteration, dtype=np.int64), points=np.asarray(points),
          controls=np.asarray([[1., 2., 3.]] if controls is None else controls))


def test_pilot_prepares_once_and_draws_only_the_newest_accepted_sample(tmp_path):
    vertices = _run(tmp_path, n=45)
    before = {p: sha256_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    binding = prepare(tmp_path, "a" * 32)
    request = binding.folder / "request.json"
    row = json.loads(request.read_text(encoding="utf-8"))
    assert row == dict(
        version=VERSION, id="a" * 32, object_id="surface", vertex_count=len(vertices),
        indices=binding.indices.tolist(),
        manifest_sha256=hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest(),
        face_budget=FACE_BUDGET,
    )
    assert 0 < len(binding.faces) <= FACE_BUDGET
    assert 0 < len(binding.target.triangles) <= FACE_BUDGET
    assert np.array_equal(np.unique(binding.indices), binding.indices)
    assert not binding.indices.flags.writeable
    shifted = vertices[binding.indices] + [0, 0, .25]
    _write_frame(binding, shifted)
    frame = read_frame(binding, 5)
    assert frame.iteration == 6 and frame.target is binding.target
    assert frame.fit.geometry_is_proxy and frame.fit.display_proxy.triangles is binding.faces
    assert np.array_equal(np.asarray(frame.fit.vertices), shifted)
    assert np.array_equal(frame.controls, [[1., 2., 3.]]) and not frame.controls.flags.writeable
    assert read_frame(binding, 6) is None
    assert before == {p: sha256_file(p) for p in before}


@pytest.mark.parametrize("budget", FACE_BUDGETS)
def test_tiers_keep_exact_native_indices_and_their_bound_frame_identity(tmp_path, budget):
    vertices = _run(tmp_path, n=130)
    binding = prepare(tmp_path, "a" * 32, face_budget=budget)
    assert binding.face_budget == binding.requested_face_budget == budget
    assert not binding.legacy_runtime and binding.protocol_version == VERSION
    assert 0 < len(binding.faces) <= budget
    assert 0 < len(binding.target.triangles) <= budget
    assert 0 < len(binding.indices) <= binding.point_limit == 3 * budget
    assert binding.target.display_proxy.budget == budget
    points = vertices[binding.indices] + [.1, .2, .3]
    _write_frame(binding, points)
    assert np.array_equal(np.asarray(read_frame(binding, 0).fit.vertices), points)
    request = json.loads((binding.folder / "request.json").read_text())
    assert request["face_budget"] == budget
    # The v2 frame must identify both its protocol and chosen display resolution.
    with np.load(binding.folder / "frame.npz") as frame:
        wrong = {name: frame[name] for name in frame.files}
    wrong["face_budget"] = np.asarray(16000 if budget != 16000 else 1600, np.int64)
    np.savez(binding.folder / "frame.npz", **wrong)
    assert read_frame(binding, 0) is None


def test_balanced_default_and_detailed_add_visible_display_geometry(tmp_path):
    _run(tmp_path, n=130)
    light = prepare(tmp_path, "a" * 32, face_budget=1600)
    balanced = prepare(tmp_path, "b" * 32)
    detailed = prepare(tmp_path, "c" * 32, face_budget=16000)
    assert balanced.face_budget == 6000
    assert len(light.faces) < len(balanced.faces) < len(detailed.faces)
    counts = [len(b.target.triangles) for b in (light, balanced, detailed)]
    assert counts[0] < counts[1] < counts[2]
    # Retirement of an earlier generation cannot retire or renew a newer one.
    release(light)
    assert not (detailed.folder / ("stop-" + detailed.identifier)).exists()
    request = json.loads((detailed.folder / "request.json").read_text())
    assert request["id"] == detailed.identifier


@pytest.mark.parametrize("requested", FACE_BUDGETS)
def test_existing_staged_v1_runtime_reports_its_light_limit_without_rewriting(tmp_path, requested):
    vertices = _run(tmp_path, n=85, version=LEGACY_VERSION)
    protected = {p: sha256_file(p) for p in tmp_path.rglob("*") if p.is_file()}
    binding = prepare(tmp_path, "a" * 32, face_budget=requested)
    assert binding.requested_face_budget == requested and binding.face_budget == 1600
    assert binding.legacy_runtime and binding.protocol_version == LEGACY_VERSION
    assert len(binding.indices) <= binding.point_limit == 4096
    row = json.loads((binding.folder / "request.json").read_text())
    assert row["version"] == LEGACY_VERSION and "face_budget" not in row
    _write_frame(binding, vertices[binding.indices])
    assert read_frame(binding, 0)
    assert protected == {p: sha256_file(p) for p in protected}


@pytest.mark.parametrize("budget", [True, 0, -1, 4096, 16001, 6000.0])
def test_unbounded_or_undeclared_resolution_is_rejected_before_writing(tmp_path, budget):
    with pytest.raises(ValueError, match="supported live preview resolution"):
        prepare(tmp_path, "a" * 32, face_budget=budget)
    assert not (tmp_path / "pilot-preview").exists()


def test_invalid_frame_members_and_old_generation_are_ignored(tmp_path):
    vertices = _run(tmp_path)
    binding = prepare(tmp_path, "b" * 32)
    points = vertices[binding.indices]
    for options in (dict(identifier="f" * 32), dict(iteration=0),
                    dict(compressed=True), dict(controls=np.zeros((129, 3)))):
        _write_frame(binding, points, **options)
        assert read_frame(binding, -1) is None
    _write_frame(binding, points[:-1])
    assert read_frame(binding, -1) is None
    _write_frame(binding, points * np.nan)
    assert read_frame(binding, -1) is None
    (binding.folder / "frame.npz").write_bytes(b"partial frame")
    assert read_frame(binding, -1) is None


def test_preview_respects_existing_runs_protected_sources_and_frame_demand(tmp_path):
    assert prepare(tmp_path, "initial-worker-request") is None
    assert not (tmp_path / "pilot-preview").exists()
    _run(tmp_path)
    manifest = tmp_path / "manifest.json"
    original_manifest = manifest.read_bytes()
    manifest.write_bytes(original_manifest + b"\n")
    with pytest.raises(ValueError, match="manifest checksum changed"):
        prepare(tmp_path, "invalid-worker-request")
    assert not (tmp_path / "pilot-preview").exists()
    manifest.write_bytes(original_manifest)
    point_file = tmp_path / "input/native.vtk"
    good_bytes = point_file.read_bytes()
    point_file.write_bytes(good_bytes + b"\n")
    with pytest.raises(ValueError, match="Protected pilot preview input changed"):
        prepare(tmp_path, "invalid-worker-request")
    assert not (tmp_path / "pilot-preview").exists()
    point_file.write_bytes(good_bytes)
    first = prepare(tmp_path, "ordinary-worker-request")
    second = prepare(tmp_path, "ordinary-worker-request")
    assert first.identifier != second.identifier
    request = second.folder / "request.json"
    old = time.time() - 20
    os.utime(request, (old, old))
    assert read_frame(first, 0) is None
    assert request.stat().st_mtime == pytest.approx(old, abs=.01)
    release(first)
    assert (first.folder / ("stop-" + first.identifier)).is_file()
    assert read_frame(second, 0) is None
    assert request.stat().st_mtime > old + 10
    assert json.loads(request.read_bytes())["id"] == second.identifier
    release(second)
