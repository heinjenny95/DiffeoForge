"""Hash-bound, memory-bounded geometry for visual alignment review."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diffeoforge.desktop.display_proxy import build_display_proxy
from diffeoforge.desktop.mesh_preview import (
    DEFAULT_GPA_TRIANGLE_BUDGET,
    MeshPreviewError,
    MeshPreviewModel,
    load_mesh_preview,
)
from diffeoforge.mesh import sha256_file
from diffeoforge.preprocessing import LandmarkAlignmentPreview

DEFAULT_COHORT_EDGE_BUDGET = 120_000
MAX_EDGES_PER_MESH = 2_500
MIN_EDGES_PER_MESH = 80


def _readonly(values: np.ndarray, *, dtype) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _bounds(vertices: np.ndarray) -> tuple[float, float, float, float, float, float]:
    minimum = np.min(vertices, axis=0)
    maximum = np.max(vertices, axis=0)
    return (
        float(minimum[0]),
        float(maximum[0]),
        float(minimum[1]),
        float(maximum[1]),
        float(minimum[2]),
        float(maximum[2]),
    )


def _aligned_model(
    source: MeshPreviewModel,
    aligned_vertices: np.ndarray,
) -> MeshPreviewModel:
    return MeshPreviewModel(
        path=source.path,
        sha256=source.sha256,
        vertices=tuple(tuple(float(value) for value in row) for row in aligned_vertices),
        triangles=source.triangles,
        edges=source.edges,
        bounds=_bounds(aligned_vertices),
        display_proxy=build_display_proxy(aligned_vertices, source.triangles),
        geometry_is_proxy=source.geometry_is_proxy,
        source_triangle_count=source.source_triangle_count,
        source_point_count=source.source_point_count,
    )


@dataclass(frozen=True)
class GpaAlignedWireframe:
    """One lightweight aligned surface used in the cohort overlay."""

    path: str
    sha256: str
    source_format: str
    vertices: np.ndarray
    triangles: np.ndarray
    edges: np.ndarray
    landmarks: np.ndarray
    squared_landmark_residual: float | None
    applied_scale: float
    source_point_count: int
    source_triangle_count: int

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices)
        triangles = np.asarray(self.triangles)
        edges = np.asarray(self.edges)
        landmarks = np.asarray(self.landmarks)
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("wireframe vertices must have shape (points, 3)")
        if triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("preview triangles must have shape (triangles, 3)")
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError("wireframe edges must have shape (edges, 2)")
        if landmarks.ndim != 2 or landmarks.shape[1] != 3:
            raise ValueError("aligned landmarks must have shape (landmarks, 3)")
        if not (
            np.isfinite(vertices).all()
            and np.isfinite(landmarks).all()
            and (
                self.squared_landmark_residual is None
                or math.isfinite(self.squared_landmark_residual)
            )
            and math.isfinite(self.applied_scale)
        ):
            raise ValueError("GPA visual data must contain only finite values")
        if self.applied_scale <= 0:
            raise ValueError("GPA visual scale must be positive")
        if edges.size and (
            int(np.min(edges)) < 0 or int(np.max(edges)) >= vertices.shape[0]
        ):
            raise ValueError("wireframe edge index is outside its vertex array")
        if triangles.size and (
            int(np.min(triangles)) < 0
            or int(np.max(triangles)) >= vertices.shape[0]
        ):
            raise ValueError("preview triangle index is outside its vertex array")
        object.__setattr__(self, "vertices", _readonly(vertices, dtype=np.float64))
        object.__setattr__(self, "triangles", _readonly(triangles, dtype=np.int64))
        object.__setattr__(self, "edges", _readonly(edges, dtype=np.int64))
        object.__setattr__(self, "landmarks", _readonly(landmarks, dtype=np.float64))


@dataclass(frozen=True)
class GpaAlignmentVisual:
    """Read-only cohort overlay bound to its input geometry."""

    fingerprint: str
    meshes: tuple[GpaAlignedWireframe, ...]
    landmark_labels: tuple[str, ...]
    mean_landmarks: np.ndarray
    bounds: tuple[float, float, float, float, float, float]
    first_detail: MeshPreviewModel
    total_displayed_edges: int
    total_source_edges: int
    total_source_triangles: int
    detail_triangle_budget: int

    def __post_init__(self) -> None:
        if len(self.fingerprint) != 64:
            raise ValueError("GPA visual fingerprint must contain 64 characters")
        if not self.meshes:
            raise ValueError("GPA visual requires at least one mesh")
        mean_landmarks = np.asarray(self.mean_landmarks)
        if mean_landmarks.shape != (len(self.landmark_labels), 3):
            raise ValueError("mean landmarks do not match their labels")
        if not np.isfinite(mean_landmarks).all():
            raise ValueError("mean landmarks must be finite")
        object.__setattr__(
            self,
            "mean_landmarks",
            _readonly(mean_landmarks, dtype=np.float64),
        )


def _verified_source_model(
    preview: LandmarkAlignmentPreview,
    index: int,
    *,
    triangle_budget: int | None = None,
) -> MeshPreviewModel:
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("mesh index must be an integer")
    if index < 0 or index >= len(preview.source_paths):
        raise IndexError("mesh index is outside the GPA cohort")
    model = load_mesh_preview(
        preview.source_paths[index],
        triangle_budget=triangle_budget,
    )
    if model.sha256 != preview.mesh_sha256[index]:
        raise MeshPreviewError(
            f"Mesh changed after the numerical GPA preview: {model.path}"
        )
    return model


def load_gpa_aligned_detail(
    preview: LandmarkAlignmentPreview,
    index: int,
    *,
    triangle_budget: int | None = None,
) -> MeshPreviewModel:
    """Load and transform one source mesh or an explicit display-only proxy."""

    source = _verified_source_model(
        preview,
        index,
        triangle_budget=triangle_budget,
    )
    vertices = np.asarray(source.vertices, dtype=np.float64)
    aligned = preview.alignment.transforms[index].apply(vertices)
    return _aligned_model(source, aligned)


def load_existing_alignment_detail(mesh: GpaAlignedWireframe) -> MeshPreviewModel:
    """Load original detail for one unchanged member of a supplied cohort."""
    source = load_mesh_preview(mesh.path)
    if source.sha256 != mesh.sha256 or source.path != Path(mesh.path):
        raise MeshPreviewError(f"Mesh changed after the alignment review was loaded: {mesh.path}")
    return source


def build_existing_alignment_visual(
    paths: tuple[Path, ...],
    *,
    cohort_edge_budget: int = DEFAULT_COHORT_EDGE_BUDGET,
    detail_triangle_budget: int = DEFAULT_GPA_TRIANGLE_BUDGET,
) -> GpaAlignmentVisual:
    """Build the ordered overlay in the supplied coordinate frame, without GPA."""
    return _build_alignment_visual(
        paths,
        preview=None,
        cohort_edge_budget=cohort_edge_budget,
        detail_triangle_budget=detail_triangle_budget,
    )


def build_gpa_alignment_visual(
    preview: LandmarkAlignmentPreview,
    *,
    cohort_edge_budget: int = DEFAULT_COHORT_EDGE_BUDGET,
    detail_triangle_budget: int = DEFAULT_GPA_TRIANGLE_BUDGET,
) -> GpaAlignmentVisual:
    """Build a deterministic all-mesh overlay without retaining full cohort meshes.

    Every surface is reduced to a bounded display-only proxy while it is loaded.
    The numerical GPA and later atlas preparation remain bound to the complete source
    files and do not consume this visualization geometry.
    """

    if not isinstance(preview, LandmarkAlignmentPreview):
        raise TypeError("preview must be a LandmarkAlignmentPreview")
    mesh_count = len(preview.source_paths)
    if not (
        mesh_count
        == len(preview.mesh_sha256)
        == len(preview.source_metadata)
        == len(preview.alignment.transforms)
        == preview.alignment.aligned_landmarks.shape[0]
    ):
        raise MeshPreviewError("Numerical GPA preview has inconsistent cohort lengths")
    return _build_alignment_visual(
        preview.source_paths,
        preview=preview,
        cohort_edge_budget=cohort_edge_budget,
        detail_triangle_budget=detail_triangle_budget,
    )


def _build_alignment_visual(
    paths: tuple[Path, ...],
    *,
    preview: LandmarkAlignmentPreview | None,
    cohort_edge_budget: int,
    detail_triangle_budget: int,
) -> GpaAlignmentVisual:
    if isinstance(cohort_edge_budget, bool) or not isinstance(
        cohort_edge_budget, int
    ):
        raise TypeError("cohort_edge_budget must be an integer")
    if cohort_edge_budget < 1:
        raise ValueError("cohort_edge_budget must be positive")
    if (
        isinstance(detail_triangle_budget, bool)
        or not isinstance(detail_triangle_budget, int)
        or detail_triangle_budget < 1
    ):
        raise ValueError("detail_triangle_budget must be a positive integer")
    mesh_count = len(paths)
    if not mesh_count:
        raise MeshPreviewError("The alignment review requires at least one surface")
    per_mesh_budget = min(
        MAX_EDGES_PER_MESH,
        max(MIN_EDGES_PER_MESH, cohort_edge_budget // mesh_count),
    )

    wireframes: list[GpaAlignedWireframe] = []
    global_minimum = np.full(3, np.inf, dtype=np.float64)
    global_maximum = np.full(3, -np.inf, dtype=np.float64)
    first_detail: MeshPreviewModel | None = None
    total_source_edges = 0
    total_source_triangles = 0
    total_displayed_edges = 0
    for index, path in enumerate(paths):
        if preview is None:
            source = load_mesh_preview(path, triangle_budget=detail_triangle_budget)
            aligned = np.asarray(source.vertices, dtype=np.float64)
            minimum, maximum = np.asarray(source.bounds, dtype=np.float64).reshape(3, 2).T
            landmarks = np.empty((0, 3), dtype=np.float64)
            residual = None
            scale = 1.0
            source_format = source.path.suffix.casefold().removeprefix(".")
            if source_format == "vtk":
                source_format = "legacy_vtk"
            source_points = source.source_point_count or source.point_count
            source_triangles = source.source_triangle_count or source.triangle_count
        else:
            source = _verified_source_model(
                preview,
                index,
                triangle_budget=detail_triangle_budget,
            )
            transform = preview.alignment.transforms[index]
            metadata = preview.source_metadata[index]
            aligned = transform.apply(np.asarray(source.vertices, dtype=np.float64))
            x_min, x_max, y_min, y_max, z_min, z_max = metadata.bounds
            source_bounds = np.asarray(
                [
                    (x, y, z)
                    for x in (x_min, x_max)
                    for y in (y_min, y_max)
                    for z in (z_min, z_max)
                ],
                dtype=np.float64,
            )
            aligned_bounds = transform.apply(source_bounds)
            minimum = np.min(aligned_bounds, axis=0)
            maximum = np.max(aligned_bounds, axis=0)
            landmarks = preview.alignment.aligned_landmarks[index]
            residual = preview.alignment.residuals[index]
            scale = transform.scale
            source_format = metadata.source_format
            source_points = metadata.points
            source_triangles = metadata.triangles

        if not (source.vertices and source.triangles and source.edges):
            raise MeshPreviewError(f"Surface has no preview geometry: {source.path}")
        global_minimum = np.minimum(global_minimum, minimum)
        global_maximum = np.maximum(global_maximum, maximum)
        if first_detail is None:
            first_detail = source if preview is None else _aligned_model(source, aligned)

        source_edges = np.asarray(source.edges, dtype=np.int64)
        if len(source_edges) > per_mesh_budget:
            selection = (
                np.arange(per_mesh_budget, dtype=np.int64)
                * len(source_edges)
                // per_mesh_budget
            )
            selected_edges = source_edges[selection]
        else:
            selected_edges = source_edges
        wireframes.append(
            GpaAlignedWireframe(
                path=str(source.path),
                sha256=source.sha256,
                source_format=source_format,
                vertices=aligned,
                triangles=np.asarray(source.triangles, dtype=np.int64),
                edges=selected_edges,
                landmarks=landmarks,
                squared_landmark_residual=residual,
                applied_scale=scale,
                source_point_count=source_points,
                source_triangle_count=source_triangles,
            )
        )
        total_source_edges += source_triangles * 3
        total_source_triangles += source_triangles
        total_displayed_edges += len(selected_edges)

    if first_detail is None or not (
        np.isfinite(global_minimum).all() and np.isfinite(global_maximum).all()
    ):
        raise MeshPreviewError("Aligned cohort has no finite visual bounds")
    span = global_maximum - global_minimum
    if float(np.max(span)) <= 0:
        raise MeshPreviewError("Aligned cohort has no positive visual extent")
    bounds = (
        float(global_minimum[0]),
        float(global_maximum[0]),
        float(global_minimum[1]),
        float(global_maximum[1]),
        float(global_minimum[2]),
        float(global_maximum[2]),
    )
    if preview is None:
        sources = [(mesh.path, mesh.sha256) for mesh in wireframes]
        for path, expected_sha256 in sources:
            if sha256_file(Path(path)) != expected_sha256:
                raise MeshPreviewError(f"Mesh changed while its alignment review was loading: {path}")
        fingerprint = hashlib.sha256(
            json.dumps(("existing-alignment-review-v1", sources)).encode("utf-8")
        ).hexdigest()
        labels = ()
        mean_landmarks = np.empty((0, 3), dtype=np.float64)
    else:
        fingerprint = preview.fingerprint
        labels = preview.landmark_labels
        mean_landmarks = preview.alignment.mean_shape
    return GpaAlignmentVisual(
        fingerprint=fingerprint,
        meshes=tuple(wireframes),
        landmark_labels=labels,
        mean_landmarks=mean_landmarks,
        bounds=bounds,
        first_detail=first_detail,
        total_displayed_edges=total_displayed_edges,
        total_source_edges=total_source_edges,
        total_source_triangles=total_source_triangles,
        detail_triangle_budget=detail_triangle_budget,
    )
