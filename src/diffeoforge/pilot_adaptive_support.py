"""Bounded support from accepted field sites and measured original-source coverage.

The resource ceiling is not a requested point count. Preserve all accepted sites,
then add only the source sites needed for coverage at the proposed kernel scale
and the largest complete accepted-field count. This is a capacity hypothesis,
not proof that an accepted composed field has an exact common representation.
"""

import math

import numpy as np

VERSION = "accepted-sites-source-coverage-v1"


def select_sites(prefix, vertices, faces, *, kernel_width, required_controls):
    from diffeoforge.pilot_multiscale import (
        AREA_SAMPLES,
        MAX_CONTROLS,
        SAMPLE_SEED,
        SOURCE_VERTEX_CANDIDATES,
    )
    from diffeoforge.reference_fit_search import surface_samples

    points = np.asarray(prefix, dtype=np.float64).copy()
    v, f = np.asarray(vertices, float), np.asarray(faces, int)
    if (points.ndim != 2 or points.shape[1:] != (3,) or not 1 <= len(points) <= MAX_CONTROLS
            or v.ndim != 2 or v.shape[1:] != (3,) or not len(v)
            or f.ndim != 2 or f.shape[1:] != (3,) or not len(f)
            or f.min() < 0 or f.max() >= len(v)
            or not np.isfinite(v).all() or not np.isfinite(points).all()
            or isinstance(kernel_width, bool) or not isinstance(kernel_width, (int, float))
            or not math.isfinite(kernel_width) or kernel_width <= 0
            or type(required_controls) is not int or not 1 <= required_controls <= MAX_CONTROLS):
        raise ValueError("Adaptive support needs finite source geometry and valid accepted demand")
    diagonal = float(np.linalg.norm(np.ptp(v, axis=0)))
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise ValueError("Adaptive support needs a nonempty original source")
    ids = (np.arange(len(v)) if len(v) <= SOURCE_VERTEX_CANDIDATES else
           np.linspace(0, len(v) - 1, SOURCE_VERTEX_CANDIDATES, dtype=np.int64))
    cloud = np.concatenate((surface_samples(v, f, AREA_SAMPLES, seed=SAMPLE_SEED), v[ids]))
    minimum = np.full(len(cloud), np.inf)
    for start in range(0, len(points), 64):
        distances = np.sum((cloud[:, None] - points[None, start:start + 64]) ** 2, axis=2)
        minimum = np.minimum(minimum, distances.min(axis=1))
    before = float(np.sqrt(minimum.max()))
    original_count, added = len(points), []
    # One Gaussian movement width is a declared coverage radius, in source units.
    # No target vertices or anatomical fit claim enter this geometric criterion.
    while len(points) < required_controls or float(np.sqrt(minimum.max())) > kernel_width:
        if len(points) == MAX_CONTROLS:
            raise ValueError(
                "Accepted sites and measured source coverage exceed the 2,000-control guard; "
                "the count is not capped silently or treated as an adequate model")
        index = int(np.argmax(minimum))
        if minimum[index] <= diagonal ** 2 * 1e-24:
            raise ValueError("Too few distinct source sites for accepted control demand")
        point = cloud[index]
        points = np.vstack((points, point))
        minimum = np.minimum(minimum, np.sum((cloud - point) ** 2, axis=1))
        added.append(index)
    return points, dict(
        version=VERSION, count=len(points), retained_sites=original_count,
        required_controls=required_controls, source_added_sites=len(added),
        coverage_radius=float(kernel_width), maximum_controls=MAX_CONTROLS,
        maximum_candidate_support_distance_before=before,
        maximum_candidate_support_distance=float(np.sqrt(minimum.max())),
        source_vertex_candidates=len(ids), area_samples=AREA_SAMPLES, sample_seed=SAMPLE_SEED,
        farthest_candidate_indices=added, target_geometry_used=False,
        momenta_transferred=False, original_surface_unchanged=True,
    )
