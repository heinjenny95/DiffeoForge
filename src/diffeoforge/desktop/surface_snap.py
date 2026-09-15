"""Bounded-memory transfer of display picks to unchanged source triangles."""

from __future__ import annotations

from threading import Event

import numpy as np


def closest_surface_point(
    point: tuple[float, float, float],
    vertices: np.ndarray,
    triangles: np.ndarray,
    *,
    cancel: Event | None = None,
    block_size: int = 32_768,
) -> tuple[float, float, float] | None:
    """Find the closest point on original faces (not just original vertices).

    Input arrays are read-only to this operation. Temporary storage is bounded
    by ``block_size``, not source resolution. A cancelled transfer returns None.
    Equidistant faces are resolved in source order for reproducibility.
    """

    query = np.asarray(point, dtype=np.float64)
    if query.shape != (3,) or not np.isfinite(query).all():
        raise ValueError("A surface pick must contain three finite coordinates")
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices must have shape (n, 3)")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles):
        raise ValueError("Original surface triangles are required for landmark transfer")
    if block_size < 1:
        raise ValueError("block_size must be positive")
    best_distance = float("inf")
    best = None
    for start in range(0, len(triangles), block_size):
        if cancel is not None and cancel.is_set():
            return None
        faces = vertices[triangles[start : start + block_size]]
        if not np.isfinite(faces).all():
            raise ValueError("Original surface contains non-finite coordinates")
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        ab, ac = b - a, c - a
        normal = np.cross(ab, ac)
        norm2 = np.einsum("ij,ij->i", normal, normal)
        denominator = np.where(norm2 > 0, norm2, 1.0)
        offset = query - a
        u = np.einsum("ij,ij->i", np.cross(offset, ac), normal) / denominator
        v = np.einsum("ij,ij->i", np.cross(ab, offset), normal) / denominator
        inside = (norm2 > 0) & (u >= 0) & (v >= 0) & (u + v <= 1)
        candidates = np.empty((len(faces), 4, 3), dtype=np.float64)
        candidates[:, 0] = a + u[:, None] * ab + v[:, None] * ac
        # Edges also cover vertices and degenerate triangles without division by zero.
        for index, (origin, end) in enumerate(((a, b), (b, c), (c, a)), start=1):
            edge = end - origin
            length2 = np.einsum("ij,ij->i", edge, edge)
            t = np.einsum("ij,ij->i", query - origin, edge) / np.where(length2 > 0, length2, 1.0)
            candidates[:, index] = origin + np.clip(t, 0, 1)[:, None] * edge
        delta = candidates - query
        distances = np.einsum("ijk,ijk->ij", delta, delta)
        distances[~inside, 0] = np.inf
        face_index, candidate_index = np.unravel_index(np.argmin(distances), distances.shape)
        distance = float(distances[face_index, candidate_index])
        if distance < best_distance:
            best_distance = distance
            best = candidates[face_index, candidate_index].copy()
    if cancel is not None and cancel.is_set():
        return None
    if best is None:
        raise ValueError("No finite original surface point could be found")
    return tuple(float(value) for value in best)
