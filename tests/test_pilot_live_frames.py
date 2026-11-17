"""Display-only requests bind native sampled points to the right prepared run."""

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.pilot_live_frames import FACE_BUDGET, VERSION, prepare, read_frame, release

pytest.importorskip("vtkmodules")


def _mesh(n=4):
    x, y = np.meshgrid(np.linspace(-1, 1, n), np.linspace(-1, 1, n))
    vertices = np.column_stack((x.ravel(), y.ravel(), (.1 * (x**2 - y**2)).ravel()))
    a = (np.arange(n - 1)[:, None] * n + np.arange(n - 1)).ravel()
    faces = np.concatenate((np.column_stack((a, a + 1, a + n)),
                            np.column_stack((a + 1, a + n + 1, a + n))))
    return vertices, faces


def _run(tmp_path: Path, n=4):
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
    runtime.write_text("# Run-local preview capability", encoding="utf-8")
    protected = [dict(path=path.relative_to(tmp_path).as_posix(), sha256=sha256_file(path))
                 for path in (source, target, model, runtime)]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(
        effective_config=dict(project=dict(parameter_provenance=dict(
            pilot_live_preview={"version": VERSION})), model=dict(object_id="surface")),
        protected_artifacts=protected,
        inputs=[dict(role="subject", staged_path="input/target.vtk")],
    )), encoding="utf-8")
    (tmp_path / "manifest.sha256").write_text(
        f"{sha256_file(manifest)}  manifest.json\n", encoding="ascii",
    )
    return v


def _write_frame(binding, points, *, iteration=6, identifier=None, controls=None, compressed=False):
    store = np.savez_compressed if compressed else np.savez
    frame_id = np.asarray(identifier or binding.identifier, dtype="U32")
    store(binding.folder / "frame.npz", id=frame_id,
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
