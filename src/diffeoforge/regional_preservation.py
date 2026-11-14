"""Material-point checks for explicitly retained areas; never anatomical approval."""

import numpy as np

from diffeoforge.regional_fit import mask

VERSION = "dense-fixed-region-v1"


def vertex_ids(points, faces, regions):
    """Cover the marked vertices and incident triangles, independent of global sampling."""
    points, faces = np.asarray(points, float), np.asarray(faces, int)
    selected = mask(points, regions)
    chosen = mask(points[faces].mean(1), regions) | selected[faces].any(1)
    return np.unique(faces[chosen])


def assess(points, reference, faces, regions, tolerance):
    points, reference = np.asarray(points, float), np.asarray(reference, float)
    if (points.shape != reference.shape or points.ndim != 2 or points.shape[1] != 3
            or not np.isfinite(points).all() or not np.isfinite(reference).all()
            or not np.isfinite(tolerance) or tolerance <= 0):
        raise ValueError("Retain-area check requires matching finite material coordinates")
    rows = []
    for index, region in enumerate(regions):
        ids = vertex_ids(reference, faces, [region])
        distances = np.linalg.norm(points[ids] - reference[ids], axis=1)
        maximum = float(distances.max()) if len(ids) else None
        rows.append(dict(region=index, vertices=len(ids), maximum=maximum,
                         passed=bool(len(ids) >= 3 and maximum <= tolerance)))
    return dict(version=VERSION, active=bool(regions), checked_vertices=sum(
        r["vertices"] for r in rows), limit=float(tolerance), regions=rows,
        maximum=max((r["maximum"] for r in rows if r["maximum"] is not None), default=0.),
        passed=all(r["passed"] for r in rows), anatomical_approval=False,
        scope="All marked starting-patch vertices, not a continuous surface/path guarantee")
