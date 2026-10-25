"""Material-point refinement preserves surfaces and rejects stale field batches."""

from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge.mesh import read_vtk_polydata, sha256_file
from diffeoforge.regional_fit import _save
from diffeoforge.source_refinement import augment, selection, subdivide


def test_new_contacts_outside_the_marked_window_still_refine_the_original_grid():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                         [.25, .25, -1], [.25, .25, 1], [.75, .75, 0]], float)
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    far = [dict(center=[20, 20, 20], radius=1)]
    original = vertices.copy()
    original[3:, 0] += 3
    selected = selection(vertices, faces, far, .1, source_vertices=original)
    assert selected.all()
    # An unchanged pre-existing contact is not a new refinement target.
    assert not selection(vertices, faces, far, .1, source_vertices=vertices).any()


@pytest.mark.parametrize("chosen", [[0], [0, 3], [0, 1, 2, 3, 4]])
def test_conforming_subdivision_preserves_material_surface_and_orientation(chosen):
    vertices, faces = map(np.asarray, cube())
    selected = np.zeros(len(faces), bool)
    selected[chosen] = True
    original_v, original_f = vertices.copy(), faces.copy()
    refined, triangles, parents = subdivide(vertices, faces, selected)
    assert np.array_equal(vertices, original_v) and np.array_equal(faces, original_f)
    assert np.array_equal(refined[: len(vertices)], vertices)
    normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                       vertices[faces[:, 2]] - vertices[faces[:, 0]])
    child = np.cross(refined[triangles[:, 1]] - refined[triangles[:, 0]],
                     refined[triangles[:, 2]] - refined[triangles[:, 0]])
    assert (np.sum(child * normals[parents], axis=1) > 0).all()
    np.testing.assert_allclose(
        np.bincount(parents, weights=np.linalg.norm(child, axis=1)),
        np.linalg.norm(normals, axis=1), atol=1e-14)
    # Every edge still has two incident faces: no nonconforming cracks.
    edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]],
                                   triangles[:, [2, 0]]]), axis=1)
    unique, count = np.unique(edges, axis=0, return_counts=True)
    assert (count == 2).all()
    assert len(refined) - len(unique) + len(triangles) == 2
    with pytest.raises(ValueError, match="vertex limit"):
        subdivide(vertices, faces, selected, maximum_vertices=len(vertices))


def test_incremental_composition_keeps_exact_old_endpoints_and_all_prefix_fields(tmp_path):
    v, f = map(np.asarray, cube())
    fine, triangles, _ = subdivide(v, f, np.arange(len(f)) == 0)
    _save(tmp_path / "old-source.vtk", v, f)
    _save(tmp_path / "grid.vtk", fine, triangles)
    previous = None
    added = None
    for i in range(2):
        old, new = tmp_path / f"old-{i}.vtk", tmp_path / f"new-{i}.vtk"
        # A nonlinear field: endpoint midpoint interpolation would give a different value.
        def flow(x, i=i):
            x = x.copy()
            x[:, 2] += (i + 1) * x[:, 0] ** 2
            return x

        _save(old, flow(v), f)
        _save(new, flow(fine[len(v):]))
        common = dict(source_run=str(i), timepoints=73, controls_sha256="q", momenta_sha256="p")
        previous = dict(common, endpoint=dict(path=str(old), sha256=sha256_file(old)),
                        prefix=previous, reference_source=dict(
                            path=str(tmp_path / "old-source.vtk"),
                            sha256=sha256_file(tmp_path / "old-source.vtk")))
        added = dict(common, endpoint=dict(path=str(new), sha256=sha256_file(new)), prefix=added)
    result = augment(previous, added, tmp_path / "grid.vtk", triangles, tmp_path / "merged")
    for level in [result, result["prefix"]]:
        mesh = read_vtk_polydata(level["endpoint"]["path"])
        original = read_vtk_polydata(level["incremental_evaluation"]["old_endpoint"]["path"])
        assert np.array_equal(mesh.vertices[: len(v)], original.vertices)
        assert np.array_equal(mesh.triangles, triangles)
    added["momenta_sha256"] = "changed"
    with pytest.raises(ValueError, match="different fitted fields"):
        augment(previous, added, tmp_path / "grid.vtk", triangles, tmp_path / "bad")


def test_field_cache_rechecks_live_identities_and_is_operation_local(tmp_path, monkeypatch):
    from diffeoforge import reference_pca
    from diffeoforge.regional_evaluation import field_inputs

    for name in ["manifest.json", "result.json", "output-inventory.json", "engine/model.xml",
                 "engine/optimization_parameters.xml", "q.txt", "p.txt", "template.vtk"]:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(name)
    data = SimpleNamespace(control_points_path=tmp_path / "q.txt", momenta_path=tmp_path / "p.txt",
                           run_report=SimpleNamespace(manifest=dict(
                               inputs=[dict(role="template", staged_path="template.vtk")])) )
    calls = []
    monkeypatch.setattr(reference_pca, "load_reference_momenta",
                        lambda *a, **kw: calls.append(True) or data)
    cache = {}
    assert field_inputs(tmp_path, cache) is field_inputs(tmp_path, cache)
    assert len(calls) == 1
    (tmp_path / "p.txt").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        field_inputs(tmp_path, cache)
    field_inputs(tmp_path, {})
    assert len(calls) == 2
