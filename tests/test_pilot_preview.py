from pathlib import Path

import numpy as np
import pytest

from diffeoforge.desktop import pilot_preview as preview
from diffeoforge.mesh import read_vtk_polydata, write_vtk_polydata


def mesh(path: Path, *, height=1.0):
    write_vtk_polydata(path, [(0, 0, 0), (1, 0, 0), (0, 1, height)], [(0, 1, 2)])
    return path


def test_cached_preview_reuses_geometry_after_reopen_and_rejects_changed_bytes(
    tmp_path, monkeypatch
):
    source = mesh(tmp_path / "mesh.vtk")
    original = source.read_bytes()
    cache = tmp_path / "display-cache"
    preview._MODELS.clear()
    first = preview.load_pilot_preview(source, cache_directory=cache)
    assert first.vertices == read_vtk_polydata(source).vertices
    assert first.triangles == ((0, 1, 2),)
    assert source.read_bytes() == original
    preview._MODELS.clear()
    monkeypatch.setattr(preview, "_classic_ascii", lambda raw: pytest.fail("Cache reparsed source"))
    second = preview.load_pilot_preview(source, cache_directory=cache)
    assert first == second
    source.write_bytes(mesh(tmp_path / "changed.vtk", height=2.0).read_bytes())
    with pytest.raises(BaseException, match="Cache reparsed"):
        preview.load_pilot_preview(source, cache_directory=cache)


def test_corrupt_cache_regenerates_and_never_supplies_invalid_geometry(tmp_path):
    source = mesh(tmp_path / "mesh.vtk")
    cache = tmp_path / "cache"
    preview._MODELS.clear()
    first = preview.load_pilot_preview(source, cache_directory=cache)
    next(cache.glob("*.npz")).write_bytes(b"corrupt cache")
    preview._MODELS.clear()
    second = preview.load_pilot_preview(source, cache_directory=cache)
    assert first == second


@pytest.mark.parametrize("bad", [b"3 0 1 8", b"3 0 0 2"])
def test_fast_preview_rejects_invalid_connectivity(tmp_path, bad):
    source = mesh(tmp_path / "bad.vtk")
    source.write_bytes(source.read_bytes().replace(b"3 0 1 2", bad))
    with pytest.raises(ValueError, match="Invalid VTK"):
        preview.load_pilot_preview(source)


def test_nonclassic_format_uses_validated_reader(tmp_path):
    source = tmp_path / "mesh.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 1\nf 1 2 3\n")
    preview._MODELS.clear()
    result = preview.load_pilot_preview(source)
    np.testing.assert_allclose(result.vertices, [(0, 0, 0), (1, 0, 0), (0, 1, 1)])
