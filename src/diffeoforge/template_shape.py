"""Rotation-independent local surface summaries for provisional template ranking."""

import numpy as np

VERSION = "local-area-neighborhoods-v1"


def local_shape_descriptor(vertices, triangles):
    """Area-sample local normal variation and occupancy at four relative scales.

    Normal signs do not matter. Equal-area sampling limits triangulation-density
    effects. No preferred feature count or anatomical orientation is encoded.
    This measures surface distribution, not homologous correspondence or fitability.
    Working arrays are bounded by 8192 samples and 256 anchors per mesh.
    """
    tri = np.asarray(vertices, dtype=float)[np.asarray(triangles, dtype=int)]
    corners = np.lexsort((tri[:, :, 2], tri[:, :, 1], tri[:, :, 0]), axis=1)
    tri = np.take_along_axis(tri, corners[:, :, None], axis=1)
    order = np.lexsort(tuple(tri.reshape(-1, 9)[:, i] for i in range(8, -1, -1)))
    tri = tri[order]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(normals, axis=1)
    keep = area > 0
    tri, normals, area = tri[keep], normals[keep], area[keep]
    if not len(tri) or not np.isfinite(tri).all() or not np.isfinite(area.sum()):
        raise ValueError("Local shape comparison requires finite positive surface area")
    weights = area / area.sum()
    center = weights @ tri.mean(axis=1)
    centered = tri - center
    sums = centered.sum(axis=1)
    radius = np.sqrt(np.sum(weights * (
        np.sum(centered * centered, axis=(1, 2)) + np.sum(sums * sums, axis=1)
    )) / 12)
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Local shape comparison requires nondegenerate geometry")
    sample_count = 8192
    positions = (np.arange(sample_count) + 0.5) / sample_count
    indices = np.minimum(np.searchsorted(np.cumsum(weights), positions), len(tri) - 1)
    rng = np.random.Generator(np.random.PCG64(7))
    u, v = np.sqrt(rng.random(sample_count)), rng.random(sample_count)
    bary = np.column_stack((1 - u, u * (1 - v), u * v))
    samples = np.einsum("ni,nij->nj", bary, centered[indices]) / radius
    normals = normals[indices] / area[indices, None]
    anchors = np.arange(0, sample_count, 32)
    distances = np.linalg.norm(samples[anchors, None] - samples[None], axis=2)
    alignment = np.abs(normals[anchors] @ normals.T)
    descriptor = []
    for scale in (0.12, 0.3, 0.6, 1.2):
        mask = distances < scale
        count = mask.sum(axis=1)
        occupancy = count / len(samples) / scale**2
        variation = 1 - np.sum(alignment * mask, axis=1) / count
        descriptor.extend(np.quantile(occupancy, (0.1, 0.5, 0.9, 0.98)))
        descriptor.extend(np.quantile(variation, (0.1, 0.5, 0.9, 0.98)))
    return tuple(float(x) for x in descriptor)


def distance_matrix(raw):
    raw = np.asarray(raw, dtype=float)
    center = np.median(raw, axis=0)
    scale = np.maximum(0.05, 1.4826 * np.median(abs(raw - center), axis=0))
    values = np.clip((raw - center) / scale, -8, 8) / np.sqrt(raw.shape[1])
    return np.linalg.norm(values[:, None] - values[None, :], axis=2)
