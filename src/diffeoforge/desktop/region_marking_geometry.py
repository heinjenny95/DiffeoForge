"""Prepare responsive marking against the exact hash-bound original surface."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
from vtkmodules.vtkCommonCore import reference, vtkPoints
from vtkmodules.vtkCommonDataModel import (
    vtkCellArray,
    vtkGenericCell,
    vtkPolyData,
    vtkStaticCellLocator,
)

from diffeoforge.desktop.display_proxy import DisplayProxy, cached_display_proxy
from diffeoforge.desktop.mesh_preview import MeshPreviewError
from diffeoforge.desktop.pilot_binary_vtk import binary_triangles
from diffeoforge.desktop.pilot_preview import (
    PILOT_DISPLAY_FACES,
    _classic_ascii,
    load_study_preview,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import mask
from diffeoforge.surface_io import load_surface_mesh

_CENTROID_BLOCK_SIZE = 32768
_RAY_ROUNDOFF = 64.0 * np.finfo(np.float64).eps


@dataclass(frozen=True, eq=False)
class RegionMarkingModel:
    """Original coordinates and separately bounded display triangles for the canvas."""

    path: Path
    sha256: str
    vertices: np.ndarray
    triangles: np.ndarray
    bounds: tuple[float, ...]
    display_proxy: DisplayProxy | None
    display_proxy_error: str | None
    geometry_is_proxy = False

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)


class RegionMarkingGeometry:
    """Exact ray intersections and indexed face-centre counts on one original mesh."""

    def __init__(self, model: RegionMarkingModel) -> None:
        self.model = model
        self._cell_locator = _cell_locator(model.vertices, model.triangles)
        self._centres = np.empty((len(model.triangles), 3), dtype=np.float64)
        for start in range(0, len(model.triangles), _CENTROID_BLOCK_SIZE):
            section = slice(start, start + _CENTROID_BLOCK_SIZE)
            self._centres[section] = model.vertices[model.triangles[section]].mean(axis=1)
        self._axes = []
        for axis in self._centres.T:
            order = np.argsort(axis)
            self._axes.append((order, axis[order]))

    def pick(self, start, end) -> tuple[float, float, float] | None:
        """Return the first original intersection from the viewer toward the scene."""
        position = [0.0] * 3
        coordinates = [0.0] * 3
        # With zero tolerance, VTK can discard a valid first hit on a spatial bin boundary.
        # Scale the roundoff allowance to the world coordinates passed to the locator.
        tolerance = _RAY_ROUNDOFF * max(map(abs, (*start, *end)))
        hit = self._cell_locator.IntersectWithLine(
            start, end, tolerance, reference(0.0), position, coordinates, reference(0),
            reference(0), vtkGenericCell(),
        )
        return tuple(position) if hit else None

    def _candidate_centres(self, region: dict) -> np.ndarray:
        """Prune by the tightest sorted coordinate range."""
        if region.get("shape") == "box":
            limits = np.asarray(region["bounds"], dtype=np.float64).reshape(3, 2)
        else:
            centre = np.asarray(region["center"], dtype=np.float64)
            radius = region["radius"]
            # Widen the pruning bounds by one float to keep boundary points.
            limits = np.column_stack((
                np.nextafter(centre - radius, -np.inf),
                np.nextafter(centre + radius, np.inf),
            ))
        candidates = None
        for (order, values), (lower, upper) in zip(self._axes, limits, strict=True):
            first = values.searchsorted(lower)
            last = values.searchsorted(upper, side="right")
            if candidates is None or last - first < len(candidates):
                candidates = order[first:last]
        return self._centres[candidates]

    def count(self, region: dict) -> int:
        """Count exact original faces using the scientific face-centre rule."""
        return int(mask(self._candidate_centres(region), [region]).sum())

    def centres_in(self, region: dict) -> np.ndarray:
        """Return original triangle centres selected by a marked area."""
        centres = self._candidate_centres(region)
        return centres[mask(centres, [region])]

    def closest_distances(self, points: np.ndarray) -> np.ndarray:
        """Measure each point to the original triangles, including face interiors."""
        squared_distances = np.empty(len(points), dtype=np.float64)
        closest = [0.0] * 3
        cell = vtkGenericCell()
        cell_id, sub_id, distance_squared = reference(0), reference(0), reference(0.0)
        for i, point in enumerate(points):
            self._cell_locator.FindClosestPoint(point, closest, cell, cell_id, sub_id,
                                                distance_squared)
            squared_distances[i] = float(distance_squared)
        return np.sqrt(squared_distances)


def _cell_locator(vertices, triangles) -> vtkStaticCellLocator:
    points = vtkPoints()
    points.SetData(numpy_to_vtk(vertices, deep=True))
    cells = vtkCellArray()
    cells.SetData(
        numpy_to_vtkIdTypeArray(np.arange(0, len(triangles) * 3 + 1, 3, dtype=np.int64), deep=True),
        numpy_to_vtkIdTypeArray(triangles.ravel(), deep=True),
    )
    surface = vtkPolyData()
    surface.SetPoints(points)
    surface.SetPolys(cells)
    locator = vtkStaticCellLocator()
    locator.SetDataSet(surface)
    locator.BuildLocator()
    return locator


def _read_triangles(source: Path, expected_sha256: str):
    if source.suffix.lower() == ".vtk":
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("The original mesh changed before area marking.")
        try:
            parsed = binary_triangles(raw)
            if parsed is None:
                lines = raw.split(b"\n", 4)
                if (len(lines) == 5
                        and lines[0].lower().startswith(b"# vtk datafile version ")
                        and lines[3].split() == [b"DATASET", b"POLYDATA"]):
                    parsed = _classic_ascii(raw)
        except (ValueError, UnicodeError):
            parsed = None  # Defer uncommon encodings to the exact surface reader.
        if parsed is not None:
            return parsed
    loaded = load_surface_mesh(source)
    if loaded.metadata.sha256 != expected_sha256:
        raise ValueError("The original mesh changed before area marking.")
    return loaded.geometry.vertices, loaded.geometry.triangles


def _reuse_proxy(preview, source_digest: str, source_faces: int) -> DisplayProxy | None:
    if preview is None or preview.sha256 != source_digest:
        return None
    proxy = preview.display_proxy
    if proxy is not None:
        if proxy.source_faces == source_faces and len(proxy.triangles) <= PILOT_DISPLAY_FACES:
            return proxy
    if (preview.geometry_is_proxy and preview.source_triangle_count == source_faces
            and 0 < preview.triangle_count <= PILOT_DISPLAY_FACES):
        arrays = tuple(np.asarray(items, dtype=dtype) for items, dtype in (
            (preview.vertices, np.float64), (preview.triangles, np.int64), (preview.edges, np.int64)
        ))
        for array in arrays:
            array.setflags(write=False)
        return DisplayProxy(*arrays, source_faces, PILOT_DISPLAY_FACES, "pilot review preview")
    return None


def _prepare(source, digest, vertices, triangles, preview=None, pilot_cache=None):
    points = np.ascontiguousarray(vertices, dtype=np.float64)
    faces = np.ascontiguousarray(triangles, dtype=np.int64)
    points, faces = points.view(), faces.view()
    points.setflags(write=False)
    faces.setflags(write=False)
    low, high = points.min(axis=0), points.max(axis=0)
    extent = np.linalg.norm(high - low)
    if not np.isfinite(extent) or extent <= 0:
        raise ValueError("The original mesh has no finite extent.")
    bounds = tuple(float(v) for v in np.column_stack((low, high)).ravel())
    proxy = None
    error = None
    if len(faces) > PILOT_DISPLAY_FACES:
        proxy = _reuse_proxy(preview, digest, len(faces))
        if proxy is None and pilot_cache is not None:
            try:
                proxy = _reuse_proxy(load_study_preview(source, pilot_cache), digest, len(faces))
            except (MeshPreviewError, OSError, ValueError):
                pass  # A display cache is optional for the verified original mesh.
        if proxy is None:
            try:
                proxy = cached_display_proxy(digest, points, faces, budget=PILOT_DISPLAY_FACES)
            except ValueError as exc:
                error = str(exc)
    model = RegionMarkingModel(source, digest, points, faces, bounds, proxy, error)
    return RegionMarkingGeometry(model)


def load_region_marking_mesh(
    original_path: Path | str,
    expected_sha256: str,
    preview_model=None,
    pilot_cache: Path | None = None,
) -> RegionMarkingGeometry:
    """Prepare the original and share its already available pilot display in a worker."""
    source = Path(original_path).expanduser().resolve()
    points, faces = _read_triangles(source, expected_sha256)
    data = _prepare(source, expected_sha256, points, faces, preview_model, pilot_cache)
    if sha256_file(source) != expected_sha256:
        raise ValueError("The original mesh changed while preparing area marking.")
    return data


def prepare_region_marking_mesh(model) -> RegionMarkingGeometry:
    """Prepare an already loaded original, for callers without a background file load."""
    if model.geometry_is_proxy:
        raise ValueError("Area marking requires the original mesh.")
    return _prepare(model.path, model.sha256, model.vertices, model.triangles, model)
