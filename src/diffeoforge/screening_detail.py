"""Conservative, recorded geometry checks for new pilot screening targets.

This is an approximation budget, not a fit/anatomical acceptance threshold or a
continuous Hausdorff certificate. Every vertex and face centroid is probed in
both directions; originals remain the fallback and the final fitting targets.
"""

from __future__ import annotations

import math

import numpy as np

VERSION = "screening-detail-v1"
KERNEL_FRACTION = 0.01
LIMITS = (
    "Discrete vertex/face-centroid distances and component counts; not a continuous "
    "surface bound, feature correspondence, anatomical approval or fit threshold."
)


def _surface(vertices, faces):
    v, f = np.asarray(vertices, dtype=float), np.asarray(faces)
    if (
        v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all()
        or f.ndim != 2 or f.shape[1] != 3 or not len(f)
        or not np.issubdtype(f.dtype, np.integer) or f.min() < 0 or f.max() >= len(v)
    ):
        raise ValueError("Screening detail needs finite triangular geometry")
    area = np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
    if not np.isfinite(area).all() or (area <= 0).any():
        raise ValueError("Screening detail needs nondegenerate triangles")
    return v, f


def component_count(faces):
    """Count face components connected through shared vertices, ignoring unused vertices."""
    parents = {}

    def find(a):
        parents.setdefault(a, a)
        while parents[a] != a:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a

    for a, b, c in faces:
        roots = [find(int(i)) for i in (a, b, c)]
        root = min(roots)
        for previous in roots:
            parents[previous] = root
    return len({find(a) for a in parents})


def measure_detail(original, working):
    from diffeoforge.reference_fit_search import distances_to_surface

    av, af = _surface(*original)
    bv, bf = _surface(*working)
    directions = []
    for v, f, target_v, target_f in ((av, af, bv, bf), (bv, bf, av, af)):
        points = np.concatenate((v, v[f].mean(axis=1)))
        distances = distances_to_surface(points, target_v, target_f)
        directions.append(dict(
            probes=len(points), maximum=float(distances.max()),
            p99=float(np.quantile(distances, 0.99)),
        ))
    return dict(
        maximum=max(row["maximum"] for row in directions),
        directions=directions,
        original_components=component_count(af), working_components=component_count(bf),
    )


def _width(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError("Screening detail requires a positive finite attachment width")
    return float(value)


def prepare_target(vertices, faces, *, attachment_width, target_faces=20_000):
    """Try bounded resolutions from originals; never accept an unmeasured decimation."""
    from diffeoforge.mesh_filter_worker import run_mesh_filter

    original = _surface(vertices, faces)
    width = _width(attachment_width)
    bound = width * KERNEL_FRACTION
    if not bound > 0 or type(target_faces) is not int or target_faces < 1:
        raise ValueError("Invalid screening approximation budget")
    receipt = dict(
        version=VERSION, attachment_width=width, kernel_fraction=KERNEL_FRACTION,
        error_budget=bound, source_faces=len(original[1]), attempts=[], limits=LIMITS,
    )
    for budget in (target_faces, target_faces * 2, target_faces * 4):
        if len(original[1]) <= budget:
            break
        attempt = dict(requested_faces=budget)
        receipt["attempts"].append(attempt)
        try:
            result = run_mesh_filter(
                "decimate", vertices=original[0], faces=original[1], budget=np.array(budget)
            )
            working = _surface(result["vertices"], result["faces"])
            if len(working[1]) >= len(original[1]):
                attempt.update(faces=len(working[1]), accepted=False, reason="no_reduction")
                break  # A larger budget cannot improve an already unreduced original.
            measured = measure_detail(original, working)
            attempt.update(faces=len(working[1]), **measured)
            accepted = (
                measured["maximum"] <= bound
                and measured["original_components"] == measured["working_components"]
            )
            attempt["accepted"] = accepted
            if accepted:
                receipt.update(status="qualified", maximum=measured["maximum"],
                               faces=len(working[1]))
                return *working, receipt
        except (RuntimeError, ValueError) as error:
            # Native filtering/measurement failure cannot license a lossy approximation.
            attempt.update(accepted=False, error=str(error))
            break
    receipt.update(status="original", maximum=0.0, faces=len(original[1]))
    return *original, receipt


def supports_width(receipt, attachment_width):
    """Reuse only a recorded checked approximation at a compatible matching scale."""
    bound = _width(attachment_width) * KERNEL_FRACTION
    if (
        not isinstance(receipt, dict) or receipt.get("version") != VERSION
        or receipt.get("status") not in {"original", "qualified"}
        or receipt.get("kernel_fraction") != KERNEL_FRACTION
    ):
        return False
    maximum = receipt.get("maximum")
    return (
        type(maximum) in (float, int) and math.isfinite(maximum) and 0 <= maximum <= bound
    )
