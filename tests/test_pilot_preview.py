from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

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


def test_existing_preview_is_reused_and_shared_after_reopen(tmp_path, monkeypatch):
    first_cache = tmp_path / "guided-pilot-trial-a" / "display-cache"
    second_cache = tmp_path / "guided-pilot-trial-b" / "display-cache"
    source = mesh(tmp_path / "source.vtk", height=3.0)
    copy = tmp_path / "copy.vtk"
    copy.write_bytes(source.read_bytes())
    old = preview.load_pilot_preview(source, cache_directory=first_cache, triangle_budget=8000)
    preview._MODELS.clear()
    monkeypatch.setattr(preview, "_classic_ascii", lambda raw: pytest.fail("Reparsed the source"))
    first = preview.load_study_preview(source, second_cache)
    assert first.sha256 == old.sha256 and first.triangles == old.triangles
    assert first.source_triangle_count == old.source_triangle_count
    assert len(tuple((tmp_path / "pilot-display-cache").glob("*-4000.npz"))) == 1
    preview._MODELS.clear()
    second = preview.load_study_preview(copy, second_cache)
    assert second.path == copy.resolve()
    assert first.sha256 == second.sha256 and first.vertices == second.vertices


def test_prefetch_and_foreground_share_one_preparation(tmp_path, monkeypatch):
    source = mesh(tmp_path / "original.vtk", height=4.0)
    copy = tmp_path / "same.vtk"
    copy.write_bytes(source.read_bytes())
    initiated, release = Event(), Event()
    actual = preview._prepare
    calls = []

    def prepare(*args):
        calls.append(args[0])
        initiated.set()
        assert release.wait(5)
        return actual(*args)

    monkeypatch.setattr(preview, "_prepare", prepare)
    preview._MODELS.clear()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(preview.load_pilot_preview, source)
        assert initiated.wait(5)
        second = executor.submit(preview.load_pilot_preview, copy)
        release.set()
        assert first.result(timeout=5).path == source.resolve()
        assert second.result(timeout=5).path == copy.resolve()
    assert calls == [source.resolve()]
