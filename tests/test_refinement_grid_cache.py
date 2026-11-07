"""Original-grid parsing reuse never weakens file or material-point binding."""

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_shape_descriptor import cube

from diffeoforge import surface_io
from diffeoforge._refinement_grid_cache import _OriginalGridCache
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _save
from diffeoforge.source_refinement import augment, subdivide


def grids(tmp_path):
    vertices, faces = map(np.asarray, cube())
    paths = [tmp_path / f"grid-{i}.vtk" for i in range(3)]
    for path in paths:
        _save(path, vertices, faces)
    calls = []

    def load(path):
        calls.append(path)
        return surface_io.load_surface_mesh(path)

    return paths, calls, load


def test_reuse_has_fresh_content_seals_and_genuinely_immutable_arrays(tmp_path):
    paths, calls, load = grids(tmp_path)
    cache = _OriginalGridCache(load)
    # The natural successful-operation exit also rechecks the last used inputs.
    with pytest.raises(ValueError, match="changed"):
        with cache:
            first = cache.get(paths[0])
            assert cache.get(paths[0]) is first
            assert len(calls) == 1
            assert first.vertices.dtype == np.dtype("float64")
            assert first.triangles.dtype == np.dtype("int64")
            for values in [first.vertices, first.triangles]:
                assert values.flags.c_contiguous
                with pytest.raises(ValueError):
                    values.setflags(write=True)
            before = paths[0].stat()
            raw = paths[0].read_bytes()
            altered = raw[:-1] + (b" " if raw[-1:] != b" " else b"\n")
            assert altered != raw and len(altered) == len(raw)
            paths[0].write_bytes(altered)
            os.utime(paths[0], ns=(before.st_atime_ns, before.st_mtime_ns))
            with pytest.raises(ValueError, match="changed|replaced"):
                cache.get(paths[0])
    assert not cache.active and not cache._entries and not cache._bindings


def test_same_bytes_size_and_mtime_do_not_hide_replacement_file_identity(tmp_path):
    paths, calls, load = grids(tmp_path)
    cache = _OriginalGridCache(load)
    with pytest.raises(ValueError, match="changed|replaced"):
        with cache:
            cache.get(paths[0])
            before = paths[0].stat()
            replacement = tmp_path / "replacement.vtk"
            replacement.write_bytes(paths[0].read_bytes())
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(paths[0])
            after = paths[0].stat()
            assert before.st_ino and after.st_ino and before.st_ino != after.st_ino
            assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            cache.get(paths[0])
    assert len(calls) == 1
    assert not cache.active and not cache._entries and not cache._bindings


def test_lru_and_byte_budget_bound_retention_without_cross_operation_reuse(tmp_path):
    paths, calls, load = grids(tmp_path)
    with _OriginalGridCache(load) as cache:
        first = cache.get(paths[0])
        size = first.vertices.nbytes + first.triangles.nbytes
        cache.get(paths[1])
        assert cache.get(paths[0]) is first  # path1 is now least recent.
        cache.get(paths[2])
        assert len(cache._entries) == 2 and cache.retained_bytes == 2 * size
        cache.get(paths[1])
        assert len(calls) == 4
    assert cache.retained_bytes == 0 and not cache._bindings
    with pytest.raises(RuntimeError, match="outside"):
        cache.get(paths[0])
    with pytest.raises(RuntimeError, match="one operation"):
        cache.__enter__()
    with _OriginalGridCache(load, maximum_bytes=size) as bounded:
        bounded.get(paths[0])
        bounded.get(paths[1])
        assert len(bounded._entries) == 1 and bounded.retained_bytes == size
    with _OriginalGridCache(load, maximum_bytes=0) as bypass:
        bypass.get(paths[0])
        bypass.get(paths[0])
        assert not bypass._entries and bypass.retained_bytes == 0
    assert len(calls) == 8


def test_exception_lifetime_and_change_during_parse_are_fail_closed(tmp_path):
    paths, _, load = grids(tmp_path)
    cache = _OriginalGridCache(load)
    with pytest.raises(InterruptedError):
        with cache:
            cache.get(paths[0])
            raise InterruptedError("operation cancelled")
    assert not cache._entries and not cache._bindings and not cache.active

    def changing_loader(path):
        loaded = load(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return loaded

    with pytest.raises(ValueError, match="during parsing"):
        with _OriginalGridCache(changing_loader) as cache:
            cache.get(paths[0])
    assert not cache._entries and not cache._bindings


def test_eviction_does_not_forget_an_earlier_source_binding(tmp_path):
    paths, _, load = grids(tmp_path)
    cache = _OriginalGridCache(load)
    with pytest.raises(ValueError, match="changed|replaced"):
        with cache:
            for path in paths:
                cache.get(path)
            assert os.path.normcase(str(paths[0])) not in cache._entries
            paths[0].write_bytes(paths[0].read_bytes() + b"\n")
            cache.get(paths[0])
    assert not cache._entries and not cache._bindings and not cache.active


@pytest.mark.parametrize("attributes", [0x400, 0x1000, 0x40000, 0x400000])
def test_unsafe_leaf_and_ancestors_are_rejected_before_loading(tmp_path, monkeypatch, attributes):
    paths, calls, load = grids(tmp_path)
    original = Path.lstat
    for unsafe_path in [paths[0], tmp_path]:
        def lstat(path, *, unsafe_path=unsafe_path):
            value = original(path)
            if path != unsafe_path:
                return value
            return SimpleNamespace(st_mode=value.st_mode, st_ino=value.st_ino,
                                   st_file_attributes=attributes)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "lstat", lstat)
            with pytest.raises(ValueError, match="ordinary|unsafe"):
                with _OriginalGridCache(load) as cache:
                    cache.get(paths[0])
    assert not calls


def test_augmentation_reuses_two_grids_but_preserves_all_prefix_bytes(tmp_path, monkeypatch):
    vertices, faces = map(np.asarray, cube())
    fine, triangles, _ = subdivide(vertices, faces, np.arange(len(faces)) == 0)
    source, grid = tmp_path / "source.vtk", tmp_path / "grid.vtk"
    _save(source, vertices, faces)
    _save(grid, fine, triangles)
    previous = added = None
    expected = []
    for i in range(3):
        def flow(values, i=i):
            values = values.copy()
            values[:, 2] += (i + 1) * values[:, 0] ** 2
            return values

        old, new, want = [tmp_path / f"{label}-{i}.vtk" for label in ["old", "new", "want"]]
        _save(old, flow(vertices), faces)
        _save(new, flow(fine[len(vertices):]))
        _save(want, flow(fine), triangles)
        expected.append(want.read_bytes())
        common = dict(source_run=str(i), timepoints=50, controls_sha256="q", momenta_sha256="p")
        previous = dict(common, endpoint=dict(path=str(old), sha256=sha256_file(old)),
                        prefix=previous, reference_source=dict(path=str(source),
                                                               sha256=sha256_file(source)),
                        untouched_metadata={"tag": i})
        added = dict(common, endpoint=dict(path=str(new), sha256=sha256_file(new)), prefix=added)
    loader, calls = surface_io.load_surface_mesh, []

    def counted(path):
        calls.append(Path(path))
        return loader(path)

    monkeypatch.setattr(surface_io, "load_surface_mesh", counted)
    for operation in range(2):
        result = augment(previous, added, grid, triangles, tmp_path / f"output-{operation}")
        for i in reversed(range(3)):
            assert Path(result["endpoint"]["path"]).read_bytes() == expected[i]
            assert result["untouched_metadata"] == {"tag": i}
            result = result["prefix"]
        assert result is None
        assert calls == [grid, source] * (operation + 1)
