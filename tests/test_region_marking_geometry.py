"""Area marking stays accurate even while the visible surface is reduced."""

import numpy as np
import pytest

from diffeoforge.desktop.mesh_preview import MeshPreviewModel
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.regional_fit import mask
from diffeoforge.surface_io import load_surface_mesh

marking = pytest.importorskip("diffeoforge.desktop.region_marking_geometry")

_POINTS = np.asarray([
    [0, 0, 1.0001], [1, 0, 1.0001], [0, 1, 1.0001],
    [0, 0, 1.0000], [1, 0, 1.0000], [0, 1, 1.0000],
])
_FACES = np.asarray([[3, 4, 5], [0, 1, 2]])


@pytest.mark.parametrize("format", ["vtk", "obj", "binary vtk"])
def test_first_ray_hit_uses_exact_source_and_handles_a_miss(tmp_path, format):
    path = tmp_path / ("original.obj" if format == "obj" else "original.vtk")
    if format == "vtk":
        write_vtk_polydata(path, _POINTS, _FACES)
    elif format == "obj":
        path.write_text("\n".join([
            *("v " + " ".join(map(str, point)) for point in _POINTS),
            *("f " + " ".join(map(str, face + 1)) for face in _FACES),
        ]), encoding="ascii")
    else:
        path.write_bytes(
            b"# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\nPOINTS 6 double\n"
            + _POINTS.astype(">f8").tobytes()
            + b"\nPOLYGONS 2 8\n"
            + np.column_stack((np.full(2, 3), _FACES)).astype(">i4").tobytes()
            + b"\n"
        )
    digest = sha256_file(path)
    data = marking.load_region_marking_mesh(path, digest)
    original = load_surface_mesh(path).geometry
    np.testing.assert_array_equal(data.model.vertices, original.vertices)
    np.testing.assert_array_equal(data.model.triangles, original.triangles)
    assert data.model.sha256 == digest and sha256_file(path) == digest
    assert not data.model.vertices.flags.writeable and not data.model.triangles.flags.writeable
    assert data.pick((.2, .3, 2), (.2, .3, 0)) == pytest.approx((.2, .3, 1.0001))
    assert data.pick((.2, .3, 0), (.2, .3, 2)) == pytest.approx((.2, .3, 1))
    assert data.pick((.8, .8, 2), (.8, .8, 0)) is None


@pytest.mark.parametrize(("scale", "gap", "tilted"), [
    (1.0, .05, False), (1e-9, 1e-9, True), (1e9, 1e-9, True),
])
def test_frontmost_ray_across_dense_overlapping_sheets(tmp_path, scale, gap, tilted):
    # Two tessellated sheets place all front triangles on the edge of the spatial index.
    grid = np.linspace(-.4, .4, 42)
    sheet = np.array([(x, y, 0.0) for y in grid for x in grid])
    indices = np.arange(len(sheet)).reshape(len(grid), -1)
    bases = indices[:-1, :-1].ravel()
    lower = np.column_stack((bases, bases + 1, bases + len(grid)))
    upper = np.column_stack((bases + 1, bases + 1 + len(grid), bases + len(grid)))
    triangles = np.vstack((lower, upper))
    rotation = (np.array([[.8, 0, -.6], [0, 1, 0], [.6, 0, .8]])
                if tilted else np.eye(3))
    offset = np.array([1e3, -2e3, 3e3]) if scale > 1 else np.zeros(3)

    def world(points):
        return (np.asarray(points) @ rotation + offset) * scale

    path = write_vtk_polydata(
        tmp_path / "sheets.vtk",
        world(np.vstack((sheet, sheet + [0, 0, gap]))),
        np.vstack((triangles, triangles + len(sheet))),
    )
    data = marking.load_region_marking_mesh(path, sha256_file(path))
    for x, y in ((0, 0), (.04, .04), (.04, .042), (grid[2], grid[5])):
        near, far = world((x, y, .8)), world((x, y, -.8))
        front = data.pick(near, far)
        back = data.pick(far, near)
        assert front is not None and back is not None
        for point, z in ((front, gap), (back, 0)):
            local = (np.asarray(point) / scale - offset) @ rotation.T
            np.testing.assert_allclose(local, [x, y, z], rtol=0, atol=5e-12)
    assert data.pick(world((.5, .5, .8)), world((.5, .5, -.8))) is None


def test_exact_counts_match_source_mask_including_boundaries(tmp_path):
    path = write_vtk_polydata(tmp_path / "layers.vtk", _POINTS, _FACES)
    data = marking.load_region_marking_mesh(path, sha256_file(path))
    centres = _POINTS[_FACES].mean(1)
    patches = [
        dict(center=centres[0], radius=np.linalg.norm(centres[1] - centres[0])),
        dict(center=centres[0], radius=0.00005),
        dict(center=[10, 10, 10], radius=1.0),
        dict(shape="box", bounds=(0, centres[0][0], 0, centres[0][1], 1, 1)),
    ]
    assert [data.count(patch) for patch in patches] == [2, 1, 0, 1]
    assert [data.count(patch) for patch in patches] == [
        int(mask(centres, [patch]).sum()) for patch in patches
    ]
    np.testing.assert_array_equal(data.centres_in(patches[1]), centres[[0]])
    np.testing.assert_allclose(
        data.closest_distances(np.array([[.2, .2, 2], [.2, .2, .5], [.2, .2, 1.0001]])),
        [.9999, .5, 0],
        atol=1e-12,
    )


def test_verified_preview_reuse_never_replaces_original_or_hides_mutation(tmp_path, monkeypatch):
    # Use a tiny simulated display budget to exercise reduced display versus exact rays.
    path = write_vtk_polydata(tmp_path / "layers.vtk", _POINTS, _FACES)
    digest = sha256_file(path)
    preview = MeshPreviewModel(
        path=path, sha256=digest, vertices=tuple(map(tuple, _POINTS[3:])),
        triangles=((0, 1, 2),), edges=((0, 1), (1, 2), (0, 2)),
        bounds=(0, 1, 0, 1, 1, 1.0001), geometry_is_proxy=True, source_triangle_count=2,
    )
    monkeypatch.setattr(marking, "PILOT_DISPLAY_FACES", 1)
    monkeypatch.setattr(marking, "cached_display_proxy", lambda *args, **kwargs: pytest.fail(
        "verified pilot display was not reused"))
    data = marking.load_region_marking_mesh(path, digest, preview)
    assert data.model.triangle_count == 2
    proxy = data.model.display_proxy
    assert proxy.source_faces == 2 and proxy.reduced
    assert len(proxy.triangles) == 1
    assert data.pick((.2, .3, 2), (.2, .3, 0)) == pytest.approx((.2, .3, 1.0001))
    with pytest.raises(ValueError, match="requires the original mesh"):
        marking.prepare_region_marking_mesh(preview)

    # A matching preview must not bypass rechecking current source bytes.
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="original mesh changed"):
        marking.load_region_marking_mesh(path, digest, preview)
