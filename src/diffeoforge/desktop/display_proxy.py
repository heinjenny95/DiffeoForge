"""Bounded, display-only reduction (no analysis geometry edits).

Desktop previews use volume-preserving quadric edge collapse rather than merging
nearby sides of a thin feature into one spatial cell. The NumPy-only headless
fallback retains bounded clustering. Both are lossy visualization, not topology
preservation, anatomical validation, or scientific mesh decimation.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

DEFAULT_DISPLAY_FACES = 8_000
_CACHE: OrderedDict[tuple[str, int], DisplayProxy] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, eq=False)
class DisplayProxy:
    vertices: np.ndarray
    triangles: np.ndarray
    edges: np.ndarray
    source_faces: int
    budget: int
    method: str

    @property
    def reduced(self) -> bool:
        return len(self.triangles) < self.source_faces


def cached_display_proxy(source_sha256: str, vertices: object, triangles: object,
                         *, budget: int = DEFAULT_DISPLAY_FACES) -> DisplayProxy:
    """Only call after verifying that geometry belongs to the exact source bytes."""
    key = source_sha256, budget
    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing is not None:
            _CACHE.move_to_end(key)
            return existing
    proxy = build_display_proxy(vertices, triangles, budget=budget)
    with _CACHE_LOCK:
        _CACHE[key] = proxy
        while _CACHE and (len(_CACHE) > 16 or sum(
            p.vertices.nbytes + p.triangles.nbytes + p.edges.nbytes for p in _CACHE.values()
        ) > _CACHE_BYTES):
            _CACHE.popitem(last=False)
    return proxy


def _check(cancelled: threading.Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Display-proxy preparation cancelled")


def _finish(
    points: np.ndarray, triangles: np.ndarray, source_faces: int, budget: int, method: str
) -> DisplayProxy:
    edges = np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, (2, 0)]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    for array in (points, triangles, edges):
        array.setflags(write=False)
    return DisplayProxy(points, triangles, edges, source_faces, budget, method)


def _quadric_edge_proxy(
    points: np.ndarray, faces: np.ndarray, budget: int,
    cancelled: threading.Event | None,
) -> DisplayProxy:
    from vtkmodules.util.numpy_support import (
        numpy_to_vtk,
        numpy_to_vtkIdTypeArray,
        vtk_to_numpy,
    )
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkFiltersCore import vtkQuadricDecimation

    vertices = vtkPoints()
    vertices.SetData(numpy_to_vtk(points, deep=True))
    cells = vtkCellArray()
    cells.SetData(
        numpy_to_vtkIdTypeArray(np.arange(0, len(faces) * 3 + 1, 3, dtype=np.int64), deep=True),
        numpy_to_vtkIdTypeArray(faces.ravel(), deep=True),
    )
    surface = vtkPolyData()
    surface.SetPoints(vertices)
    surface.SetPolys(cells)
    reducer = vtkQuadricDecimation()
    reducer.SetInputData(surface)
    reducer.SetTargetReduction(1 - max(1, budget - 2) / len(faces))
    reducer.VolumePreservationOn()

    def observe_cancel(caller, _event):
        if cancelled is not None and cancelled.is_set():
            caller.AbortExecuteOn()

    reducer.AddObserver("ProgressEvent", observe_cancel)
    _check(cancelled)
    reducer.Update()
    _check(cancelled)
    output = reducer.GetOutput()
    if not output.GetNumberOfPoints() or not 0 < output.GetNumberOfPolys() <= budget:
        raise ValueError("No bounded display proxy available; inspect original detail explicitly")
    offsets = vtk_to_numpy(output.GetPolys().GetOffsetsArray())
    if not np.all(np.diff(offsets) == 3):
        raise ValueError("Display reduction returned non-triangular geometry")
    result_faces = vtk_to_numpy(output.GetPolys().GetConnectivityArray()).reshape(-1, 3)
    used, compact = np.unique(result_faces, return_inverse=True)
    result_points = vtk_to_numpy(output.GetPoints().GetData())[used].copy()
    if not np.isfinite(result_points).all():
        raise ValueError("Display reduction returned non-finite geometry")
    result_points = np.clip(result_points, points.min(axis=0), points.max(axis=0))
    _check(cancelled)
    return _finish(
        result_points, compact.reshape(-1, 3), len(faces), budget,
        "quadric edge collapse; display only",
    )


def build_display_proxy(
    vertices: object,
    triangles: object,
    *,
    budget: int = DEFAULT_DISPLAY_FACES,
    cancelled: threading.Event | None = None,
) -> DisplayProxy:
    """Return immutable display arrays; all expensive calls belong in a worker.

    The hard budget never falls back to silently rendering a large full surface.
    A mesh whose disconnected/tiny geometry cannot survive clustering raises a
    visible error so the caller can offer explicit original-detail inspection.
    """
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("Display face budget must be a positive integer")
    points = np.array(vertices, dtype=np.float64, copy=True).reshape(-1, 3)
    faces = np.array(triangles, dtype=np.int64, copy=True).reshape(-1, 3)
    _check(cancelled)
    if not len(points) or not len(faces) or not np.isfinite(points).all():
        raise ValueError("Display geometry must contain finite points and faces")
    if faces.min() < 0 or faces.max() >= len(points):
        raise ValueError("Display face index outside vertex array")
    if len(faces) <= budget:
        return _finish(points, faces, len(faces), budget, "original")
    origin = points.min(axis=0)
    span = float(np.ptp(points, axis=0).max())
    if not span > 0:
        raise ValueError("Display geometry has no spatial extent")
    try:
        return _quadric_edge_proxy(points, faces, budget, cancelled)
    except ModuleNotFoundError as error:
        # VTK is a required desktop dependency. Keep the NumPy-only library
        # usable in headless environments without importing optional GUI stacks.
        if not error.name or not error.name.startswith("vtk"):
            raise
    normalized = (points - origin) / span
    # Resolution decreases monotonically. At most ten bounded clustering passes;
    # no source faces are dropped by uniform sampling to hit the final budget.
    resolution = max(2, int(np.sqrt(budget)))
    for _ in range(10):
        _check(cancelled)
        cells = np.floor(normalized * resolution).astype(np.int64)
        _, inverse = np.unique(cells, axis=0, return_inverse=True)
        collapsed = inverse[faces]
        valid = (
            (collapsed[:, 0] != collapsed[:, 1])
            & (collapsed[:, 1] != collapsed[:, 2])
            & (collapsed[:, 2] != collapsed[:, 0])
        )
        candidate = collapsed[valid]
        if len(candidate):
            _, first = np.unique(np.sort(candidate, axis=1), axis=0, return_index=True)
            candidate = candidate[np.sort(first)]
        if 0 < len(candidate) <= budget:
            break
        if resolution <= 1:
            raise ValueError(
                "No bounded display proxy available; inspect original detail explicitly"
            )
        resolution = max(1, int(resolution * 0.62))
    else:
        raise ValueError("Display proxy exceeded its preparation budget")
    _check(cancelled)
    count = int(inverse.max()) + 1
    weights = np.bincount(inverse, minlength=count)
    centroids = np.column_stack(
        [
            np.bincount(inverse, weights=normalized[:, axis], minlength=count) / weights
            for axis in range(3)
        ]
    )
    # Accumulate area-weighted plane quadrics without N x N products.
    triangles_xyz = normalized[faces]
    normals = np.cross(
        triangles_xyz[:, 1] - triangles_xyz[:, 0], triangles_xyz[:, 2] - triangles_xyz[:, 0]
    )
    areas = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(areas[:, None], np.finfo(float).eps)
    offsets = np.einsum("ij,ij->i", normals, triangles_xyz[:, 0])
    groups = inverse[faces].ravel()
    matrix = np.zeros((count, 3, 3))
    vector = np.zeros((count, 3))
    for a in range(3):
        _check(cancelled)
        vector[:, a] = np.bincount(
            groups, np.repeat(areas * normals[:, a] * offsets, 3), minlength=count
        )
        for b in range(3):
            matrix[:, a, b] = np.bincount(
                groups, np.repeat(areas * normals[:, a] * normals[:, b], 3), minlength=count
            )
    regularizer = np.maximum(np.trace(matrix, axis1=1, axis2=2) * 1e-5, 1e-12)
    matrix += regularizer[:, None, None] * np.eye(3)
    vector += regularizer[:, None] * centroids
    representatives = np.linalg.solve(matrix, vector[..., None])[..., 0]
    low = np.full((count, 3), np.inf)
    high = np.full((count, 3), -np.inf)
    np.minimum.at(low, inverse, normalized)
    np.maximum.at(high, inverse, normalized)
    representatives = np.clip(representatives, low, high)
    used, compact = np.unique(candidate, return_inverse=True)
    output = representatives[used] * span + origin
    _check(cancelled)
    return _finish(
        output,
        compact.reshape(-1, 3),
        len(faces),
        budget,
        "quadric vertex clustering; display only",
    )
