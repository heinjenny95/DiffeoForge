"""Bounded, deterministic surface-shape coverage; not anatomical correspondence."""

from __future__ import annotations

import itertools

import numpy as np

SHAPE_DESCRIPTOR_VERSION = "aligned-area-shape-v1"
SHAPE_SAMPLE_COUNT = 4096


def surface_shape_descriptor(vertices, triangles) -> tuple[float, ...]:
    """Describe shape independently of translation, uniform scale and vertex density.

    Retain the declared anatomical orientation (do not independently PCA-align or
    reflect specimens). Exact area centroid/second moments normalize the surface;
    directional supports retain small protrusions and area-uniform samples describe
    the surface distribution, including non-convex regions. No mesh is modified.
    Sampling is reproducible after face/vertex reordering, not exactly invariant to
    retriangulation. A descriptor is a coverage heuristic, never a fit/QC verdict.
    """
    points = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    tri = points[faces]
    if not np.isfinite(tri).all():
        raise ValueError("Shape descriptors require finite surface coordinates")
    # Canonical triangle and corner order avoids dependence on STL/VTK ordering.
    corners = np.lexsort((tri[:, :, 2], tri[:, :, 1], tri[:, :, 0]), axis=1)
    tri = np.take_along_axis(tri, corners[:, :, None], axis=1)
    centers = tri.mean(axis=1)
    order = np.lexsort(tuple(tri.reshape(-1, 9)[:, i] for i in range(8, -1, -1)))
    tri, centers = tri[order], centers[order]
    areas = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    keep = areas > 0
    tri, centers, areas = tri[keep], centers[keep], areas[keep]
    total = areas.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("Shape descriptors require positive finite surface area")
    weights = areas / total
    center = weights @ centers
    tri = tri - center
    sums = tri.sum(axis=1)
    covariance = (
        np.einsum("n,nki,nkj->ij", weights, tri, tri)
        + np.einsum("n,ni,nj->ij", weights, sums, sums)
    ) / 12.0
    radius = float(np.sqrt(np.trace(covariance)))
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Shape descriptors require a nondegenerate surface")
    normalized = (points[np.unique(faces)] - center) / radius
    eigenvalues = np.maximum(0, np.linalg.eigvalsh(covariance)) / radius**2
    directions = np.asarray(
        [d for d in itertools.product((-1, 0, 1), repeat=3) if any(d)], dtype=float
    )
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    supports = np.asarray([np.max(normalized @ direction) for direction in directions])

    rng = np.random.Generator(np.random.PCG64(0))
    # Stratification bounds sampling variance without favoring densely meshed areas.
    positions = (np.arange(SHAPE_SAMPLE_COUNT) + 0.5) / SHAPE_SAMPLE_COUNT
    chosen = np.minimum(np.searchsorted(np.cumsum(weights), positions), len(tri) - 1)
    u = np.sqrt(rng.random(SHAPE_SAMPLE_COUNT))
    v = rng.random(SHAPE_SAMPLE_COUNT)
    barycentric = np.column_stack((1 - u, u * (1 - v), u * v))
    samples = np.einsum("ni,nij->nj", barycentric, tri[chosen]) / radius
    radial = np.quantile(np.linalg.norm(samples, axis=1), np.linspace(0.1, 0.9, 9))
    # Smooth directional surface-distribution quantiles capture more than a hull.
    projected = samples @ directions.T
    quantiles = np.quantile(projected, (0.1, 0.25, 0.5, 0.75, 0.9), axis=0).ravel()
    return tuple(
        float(value) for value in np.concatenate((eigenvalues, supports, radial, quantiles))
    )


def normalized_shape_matrix(descriptors) -> np.ndarray:
    """Equal family weights and a fixed noise floor prevent tiny differences exploding."""
    raw = np.asarray(descriptors, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] != 168 or not np.isfinite(raw).all():
        raise ValueError("Invalid aligned-area-shape-v1 descriptor")
    center = np.median(raw, axis=0)
    scale = np.maximum(0.05, 1.4826 * np.median(np.abs(raw - center), axis=0))
    result = np.clip((raw - center) / scale, -8, 8)
    for start, end in ((0, 3), (3, 29), (29, 38), (38, 168)):
        result[:, start:end] /= np.sqrt(end - start)
    return result
