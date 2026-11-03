"""A small protrusion must remain visible in a settled review preview."""

from __future__ import annotations

import builtins
import gc
import threading
import weakref

import numpy as np
import pytest

from diffeoforge.desktop.display_proxy import build_display_proxy


def thin_protrusion():
    nphi, ntheta = 180, 360
    phi = np.arange(1, nphi + 1)[:, None] * np.pi / (nphi + 1)
    theta = np.arange(ntheta)[None, :] * 2 * np.pi / ntheta
    rings = np.stack(
        np.broadcast_arrays(np.sin(phi) * np.cos(theta), np.sin(phi) * np.sin(theta), np.cos(phi)),
        axis=-1,
    )
    unit = np.vstack(([0.0, 0.0, 1.0], rings.reshape(-1, 3), [0.0, 0.0, -1.0]))
    direction = np.array([0.28, 0.43, 0.858])
    direction /= np.linalg.norm(direction)
    angle = np.arccos(np.clip(unit @ direction, -1, 1))
    width = 0.04
    points = unit * (1 + 0.8 * np.exp(-((angle / width) ** 2)))[:, None]
    a = 1 + np.arange((nphi - 1) * ntheta)
    b = 1 + (a - 1) // ntheta * ntheta + (a % ntheta)
    c, e = a + ntheta, b + ntheta
    first = 1 + np.arange(ntheta)
    last = first + (nphi - 1) * ntheta
    faces = np.vstack(
        (
            np.column_stack((a, c, b)),
            np.column_stack((b, c, e)),
            np.column_stack((np.zeros(ntheta, dtype=int), first, np.roll(first, -1))),
            np.column_stack((np.full(ntheta, len(points) - 1), np.roll(last, -1), last)),
        )
    )
    return points, faces, angle < width * 2, width


def test_review_proxy_keeps_a_thin_protrusion_within_half_its_width():
    vtk = pytest.importorskip("vtk")
    from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

    points, faces, feature, width = thin_protrusion()
    preview = build_display_proxy(points, faces)
    assert len(preview.triangles) <= 8000
    mesh = vtk.vtkPolyData()
    vertices = vtk.vtkPoints()
    vertices.SetData(numpy_to_vtk(preview.vertices, deep=True))
    mesh.SetPoints(vertices)
    cells = vtk.vtkCellArray()
    cells.SetData(
        numpy_to_vtkIdTypeArray(
            np.arange(0, len(preview.triangles) * 3 + 1, 3, dtype=np.int64), deep=True
        ),
        numpy_to_vtkIdTypeArray(
            preview.triangles.astype(np.int64).ravel(),
            deep=True,
        ),
    )
    mesh.SetPolys(cells)
    locator = vtk.vtkStaticCellLocator()
    locator.SetDataSet(mesh)
    locator.BuildLocator()
    closest = [0.0, 0.0, 0.0]
    cell = vtk.mutable(0)
    sub = vtk.mutable(0)
    distance = vtk.mutable(0.0)
    errors = []
    for point in points[feature]:
        locator.FindClosestPoint(point, closest, cell, sub, distance)
        errors.append(float(distance) ** 0.5)
    assert max(errors) <= width / 2


def test_native_reduction_observes_cancellation_before_returning_a_proxy(monkeypatch):
    filters = pytest.importorskip("vtkmodules.vtkFiltersCore")
    native = filters.vtkQuadricDecimation
    cancelled = threading.Event()
    observed = []

    def observed_filter():
        instance = native()

        def stop(_caller, _event):
            observed.append(True)
            cancelled.set()

        instance.AddObserver("ProgressEvent", stop)
        return instance

    monkeypatch.setattr(filters, "vtkQuadricDecimation", observed_filter)
    points, faces, _, _ = thin_protrusion()
    with pytest.raises(InterruptedError):
        build_display_proxy(points, faces, cancelled=cancelled)
    assert observed


def test_headless_preview_keeps_its_bounded_numpy_fallback(monkeypatch):
    original = builtins.__import__

    def without_vtk(name, *args, **kwargs):
        if name.startswith("vtk"):
            raise ModuleNotFoundError("No optional VTK stack", name="vtkmodules")
        return original(name, *args, **kwargs)

    points, faces, _, _ = thin_protrusion()
    before = points.copy()
    monkeypatch.setattr(builtins, "__import__", without_vtk)
    result = build_display_proxy(points, faces)
    assert 0 < len(result.triangles) <= 8000
    assert "clustering" in result.method
    assert np.array_equal(points, before)


def test_native_preview_releases_its_filter_and_input_geometry(monkeypatch):
    filters = pytest.importorskip("vtkmodules.vtkFiltersCore")
    native = filters.vtkQuadricDecimation
    references = []

    def observed_filter():
        instance = native()
        references.append(weakref.ref(instance))
        return instance

    monkeypatch.setattr(filters, "vtkQuadricDecimation", observed_filter)
    points, faces, _, _ = thin_protrusion()
    preview = build_display_proxy(points, faces, cancelled=threading.Event())
    gc.collect()
    assert len(preview.triangles) <= 8000
    assert references and all(reference() is None for reference in references)
