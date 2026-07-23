"""Immutable, read-only orthographic template preview data for the desktop."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.surface_io import load_surface_mesh

DEFAULT_EDGE_BUDGET = 20_000
PreviewPlane = Literal["xy", "xz", "yz"]
_PLANE_AXES: dict[PreviewPlane, tuple[int, int]] = {
    "xy": (0, 1),
    "xz": (0, 2),
    "yz": (1, 2),
}
_AXIS_BOUNDS = ((0, 1), (2, 3), (4, 5))


class MeshPreviewError(RuntimeError):
    """Raised when a mesh cannot produce a trustworthy inspection preview."""


@dataclass(frozen=True)
class ProjectedMeshPreview:
    """One aspect-preserving normalized orthographic projection."""

    plane: PreviewPlane
    source_vertex_indices: tuple[int, ...]
    points: tuple[tuple[float, float], ...]
    edges: tuple[tuple[int, int], ...]
    total_edge_count: int

    @property
    def displayed_edge_count(self) -> int:
        return len(self.edges)

    @property
    def sampled(self) -> bool:
        return self.displayed_edge_count < self.total_edge_count


@dataclass(frozen=True)
class MeshPreviewModel:
    """Exact source identity and immutable geometry used by every preview plane."""

    path: Path
    sha256: str
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    edges: tuple[tuple[int, int], ...]
    bounds: tuple[float, float, float, float, float, float]

    @property
    def point_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def project(
        self,
        plane: PreviewPlane,
        *,
        edge_budget: int = DEFAULT_EDGE_BUDGET,
    ) -> ProjectedMeshPreview:
        """Return a deterministic projection without changing or rereading the mesh."""

        if plane not in _PLANE_AXES:
            raise MeshPreviewError(f"Unsupported preview plane: {plane!r}")
        if isinstance(edge_budget, bool) or not isinstance(edge_budget, int):
            raise TypeError("edge_budget must be an integer")
        if edge_budget <= 0:
            raise ValueError("edge_budget must be positive")

        horizontal, vertical = _PLANE_AXES[plane]
        horizontal_bounds = _AXIS_BOUNDS[horizontal]
        vertical_bounds = _AXIS_BOUNDS[vertical]
        horizontal_min = self.bounds[horizontal_bounds[0]]
        horizontal_max = self.bounds[horizontal_bounds[1]]
        vertical_min = self.bounds[vertical_bounds[0]]
        vertical_max = self.bounds[vertical_bounds[1]]
        horizontal_span = horizontal_max - horizontal_min
        vertical_span = vertical_max - vertical_min
        scale = max(horizontal_span, vertical_span)
        if not math.isfinite(scale) or scale <= 0:
            raise MeshPreviewError(
                f"Template has no finite extent in the {plane.upper()} preview plane"
            )
        horizontal_center = (horizontal_min + horizontal_max) / 2.0
        vertical_center = (vertical_min + vertical_max) / 2.0
        if self.edge_count <= edge_budget:
            selected = self.edges
        else:
            selected = tuple(
                self.edges[index * self.edge_count // edge_budget]
                for index in range(edge_budget)
            )
        source_vertex_indices = tuple(
            sorted({vertex for edge in selected for vertex in edge})
        )
        local_index = {
            source_index: index
            for index, source_index in enumerate(source_vertex_indices)
        }
        points = tuple(
            (
                2.0
                * (self.vertices[index][horizontal] - horizontal_center)
                / scale,
                -2.0
                * (self.vertices[index][vertical] - vertical_center)
                / scale,
            )
            for index in source_vertex_indices
        )
        projected_edges = tuple(
            (local_index[start], local_index[end]) for start, end in selected
        )
        return ProjectedMeshPreview(
            plane=plane,
            source_vertex_indices=source_vertex_indices,
            points=points,
            edges=projected_edges,
            total_edge_count=self.edge_count,
        )


def _unique_edges(
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, int], ...]:
    edges: set[tuple[int, int]] = set()
    for a, b, c in triangles:
        edges.update(
            (
                (min(a, b), max(a, b)),
                (min(b, c), max(b, c)),
                (min(c, a), max(c, a)),
            )
        )
    return tuple(sorted(edges))


def load_mesh_preview(path: Path | str) -> MeshPreviewModel:
    """Load one exact supported surface and reject concurrent source changes."""

    source = Path(path).expanduser().resolve()
    try:
        hash_before = sha256_file(source)
        loaded = load_surface_mesh(source)
        hash_after = sha256_file(source)
    except (ConfigurationError, OSError, TypeError, ValueError) as error:
        raise MeshPreviewError(f"Template preview could not read {source}: {error}") from error
    metadata = loaded.metadata
    geometry = loaded.geometry
    if hash_before != metadata.sha256 or hash_before != hash_after:
        raise MeshPreviewError("Template changed while its preview model was loaded")
    if len(geometry.vertices) != metadata.points:
        raise MeshPreviewError("Template point count changed while preview was loaded")
    if len(geometry.triangles) != metadata.triangles:
        raise MeshPreviewError("Template triangle count changed while preview was loaded")
    return MeshPreviewModel(
        path=source,
        sha256=hash_after,
        vertices=geometry.vertices,
        triangles=geometry.triangles,
        edges=_unique_edges(geometry.triangles),
        bounds=metadata.bounds,
    )
