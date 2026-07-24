"""Hash-bound, memory-bounded geometry for visual GPA review."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from diffeoforge.desktop.mesh_preview import (
    MeshPreviewError,
    MeshPreviewModel,
    load_mesh_preview,
)
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
    )


@dataclass(frozen=True)
class GpaAlignedWireframe:
    """One lightweight aligned surface used in the cohort overlay."""

    path: str
    sha256: str
    source_format: str
    vertices: np.ndarray
    edges: np.ndarray
    landmarks: np.ndarray
    squared_landmark_residual: float
    applied_scale: float
    source_point_count: int
    source_triangle_count: int

    def __post_init__(self) -> None:
        vertices = np.asarray(self.vertices)
        edges = np.asarray(self.edges)
        landmarks = np.asarray(self.landmarks)
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("wireframe vertices must have shape (points, 3)")
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError("wireframe edges must have shape (edges, 2)")
        if landmarks.ndim != 2 or landmarks.shape[1] != 3:
            raise ValueError("aligned landmarks must have shape (landmarks, 3)")
        if not (
            np.isfinite(vertices).all()
            and np.isfinite(landmarks).all()
            and math.isfinite(self.squared_landmark_residual)
            and math.isfinite(self.applied_scale)
        ):
            raise ValueError("GPA visual data must contain only finite values")
        if self.applied_scale <= 0:
            raise ValueError("GPA visual scale must be positive")
        if edges.size and (
            int(np.min(edges)) < 0 or int(np.max(edges)) >= vertices.shape[0]
        ):
            raise ValueError("wireframe edge index is outside its vertex array")
        object.__setattr__(self, "vertices", _readonly(vertices, dtype=np.float64))
        object.__setattr__(self, "edges", _readonly(edges, dtype=np.int64))
        object.__setattr__(self, "landmarks", _readonly(landmarks, dtype=np.float64))


@dataclass(frozen=True)
class GpaAlignmentVisual:
    """Read-only cohort overlay bound to one numerical GPA preview."""

    fingerprint: str
    meshes: tuple[GpaAlignedWireframe, ...]
    landmark_labels: tuple[str, ...]
    mean_landmarks: np.ndarray
    bounds: tuple[float, float, float, float, float, float]
    first_detail: MeshPreviewModel
    total_displayed_edges: int
    total_source_edges: int

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
) -> MeshPreviewModel:
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("mesh index must be an integer")
    if index < 0 or index >= len(preview.source_paths):
        raise IndexError("mesh index is outside the GPA cohort")
    model = load_mesh_preview(preview.source_paths[index])
    if model.sha256 != preview.mesh_sha256[index]:
        raise MeshPreviewError(
            f"Mesh changed after the numerical GPA preview: {model.path}"
        )
    return model


def load_gpa_aligned_detail(
    preview: LandmarkAlignmentPreview,
    index: int,
) -> MeshPreviewModel:
    """Load and transform one complete source mesh for detailed inspection."""

    source = _verified_source_model(preview, index)
    vertices = np.asarray(source.vertices, dtype=np.float64)
    aligned = preview.alignment.transforms[index].apply(vertices)
    return _aligned_model(source, aligned)


def build_gpa_alignment_visual(
    preview: LandmarkAlignmentPreview,
    *,
    cohort_edge_budget: int = DEFAULT_COHORT_EDGE_BUDGET,
) -> GpaAlignmentVisual:
    """Build a deterministic all-mesh overlay without retaining full cohort meshes."""

    if not isinstance(preview, LandmarkAlignmentPreview):
        raise TypeError("preview must be a LandmarkAlignmentPreview")
    if isinstance(cohort_edge_budget, bool) or not isinstance(
        cohort_edge_budget, int
    ):
        raise TypeError("cohort_edge_budget must be an integer")
    if cohort_edge_budget < 1:
        raise ValueError("cohort_edge_budget must be positive")
    mesh_count = len(preview.source_paths)
    if not (
        mesh_count
        == len(preview.mesh_sha256)
        == len(preview.source_metadata)
        == len(preview.alignment.transforms)
        == preview.alignment.aligned_landmarks.shape[0]
    ):
        raise MeshPreviewError("Numerical GPA preview has inconsistent cohort lengths")
    per_mesh_budget = min(
        MAX_EDGES_PER_MESH,
        max(MIN_EDGES_PER_MESH, cohort_edge_budget // mesh_count),
    )

    wireframes: list[GpaAlignedWireframe] = []
    global_minimum = np.full(3, np.inf, dtype=np.float64)
    global_maximum = np.full(3, -np.inf, dtype=np.float64)
    first_detail: MeshPreviewModel | None = None
    total_source_edges = 0
    total_displayed_edges = 0
    for index in range(mesh_count):
        source = _verified_source_model(preview, index)
        vertices = np.asarray(source.vertices, dtype=np.float64)
        aligned = preview.alignment.transforms[index].apply(vertices)
        global_minimum = np.minimum(global_minimum, np.min(aligned, axis=0))
        global_maximum = np.maximum(global_maximum, np.max(aligned, axis=0))
        if first_detail is None:
            first_detail = _aligned_model(source, aligned)

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
        source_vertex_indices, inverse = np.unique(
            selected_edges.reshape(-1),
            return_inverse=True,
        )
        local_edges = inverse.reshape(-1, 2)
        wireframes.append(
            GpaAlignedWireframe(
                path=str(source.path),
                sha256=source.sha256,
                source_format=preview.source_metadata[index].source_format,
                vertices=aligned[source_vertex_indices],
                edges=local_edges,
                landmarks=preview.alignment.aligned_landmarks[index],
                squared_landmark_residual=preview.alignment.residuals[index],
                applied_scale=preview.alignment.transforms[index].scale,
                source_point_count=source.point_count,
                source_triangle_count=source.triangle_count,
            )
        )
        total_source_edges += len(source.edges)
        total_displayed_edges += len(local_edges)

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
    return GpaAlignmentVisual(
        fingerprint=preview.fingerprint,
        meshes=tuple(wireframes),
        landmark_labels=preview.landmark_labels,
        mean_landmarks=preview.alignment.mean_shape,
        bounds=bounds,
        first_detail=first_detail,
        total_displayed_edges=total_displayed_edges,
        total_source_edges=total_source_edges,
    )
