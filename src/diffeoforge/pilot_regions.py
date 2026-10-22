"""Source-bound 3D feedback and diagnostic measurements, never attachment weights."""

from __future__ import annotations

import math

import numpy as np

VERSION = "surface-region-v1"
SYMPTOMS = {
    "detail": "Details are missing",
    "missing": "Part of the surface is missed",
    "shape": "The shape or position is wrong",
    "distortion": "The reconstruction looks distorted",
    "unsure": "I am unsure what is wrong",
}
MAX_REGIONS = 8


def validate(regions, sources):
    """Reject stale identities and malformed feedback before journalling/reuse."""
    if not isinstance(regions, dict) or set(regions) - set(sources):
        raise ValueError("Problem regions must name inspected original specimens")
    result = {}
    for name, rows in regions.items():
        if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= MAX_REGIONS:
            raise ValueError("Keep between one and eight regions per specimen")
        result[name] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "version",
                "source_sha256",
                "space",
                "center",
                "radius",
                "symptom",
            }:
                raise ValueError("Invalid 3D region record")
            center, radius = row["center"], row["radius"]
            if (
                row["version"] != VERSION
                or row["space"] != "original_mesh_coordinates"
                or row["source_sha256"] != sources[name]
                or not isinstance(row["symptom"], str)
                or row["symptom"] not in SYMPTOMS
                or not isinstance(center, (list, tuple))
                or len(center) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in center)
                or type(radius) not in (int, float)
                or not math.isfinite(radius)
                or radius <= 0
            ):
                raise ValueError("Region source, coordinates, size or symptom changed")
            result[name].append(dict(row, center=list(center)))
    return result


def face_mask(vertices, faces, center, radius):
    """A surface brush selects whole faces by their centres in original 3D space."""
    centres = np.asarray(vertices, float)[np.asarray(faces, int)].mean(axis=1)
    return np.linalg.norm(centres - np.asarray(center, float), axis=1) <= radius


def measure(original, reconstruction, regions):
    """Sample every marked patch directly, including patches missed by a global sample.

    Reverse distances use reconstructed samples in the same 3D sphere. An empty
    reverse sample is unknown, never a zero error or proof of correspondence.
    """
    from diffeoforge.reference_fit_search import distances_to_surface, surface_samples

    av, af = np.asarray(original.vertices, float), np.asarray(original.triangles, int)
    bv, bf = np.asarray(reconstruction.vertices, float), np.asarray(reconstruction.triangles, int)
    diagonal = float(np.linalg.norm(np.ptp(av, axis=0)))
    result = []
    for row in regions:
        mask = face_mask(av, af, row["center"], row["radius"])
        if not mask.any():
            raise ValueError("The marked brush contains no original face centres; enlarge it")
        repeats = []
        for seed in (20261022, 20261023):
            points = surface_samples(av, af[mask], 2048, seed=seed)
            distances = distances_to_surface(points, bv, bf)
            reverse = surface_samples(bv, bf, 8192, seed=seed)
            reverse = reverse[np.linalg.norm(reverse - row["center"], axis=1) <= row["radius"]]
            back = distances_to_surface(reverse, av, af) if len(reverse) else None
            repeats.append(
                dict(
                    original_to_fit_p95=float(np.quantile(distances, 0.95)),
                    original_to_fit_p99=float(np.quantile(distances, 0.99)),
                    fit_to_original_p95=float(np.quantile(back, 0.95))
                    if back is not None
                    else None,
                    reverse_count=len(reverse),
                )
            )
        result.append(
            dict(region=row, selected_faces=int(mask.sum()), diagonal=diagonal, repeats=repeats)
        )
    return result


def comparison(before, after, global_before, global_after):
    """Conservative feedback; no automatic anatomical approval or method selection."""
    if len(before) != len(after) or any(
        a["region"] != b["region"] for a, b in zip(before, after, strict=True)
    ):
        raise ValueError("Regional comparisons require identical original patches")
    improved, worsened = False, False
    for a, b in zip(before, after, strict=True):
        floor = a["diagonal"] * 1e-6
        for key in ("original_to_fit_p95", "original_to_fit_p99", "fit_to_original_p95"):
            x = [r[key] for r in a["repeats"] if r[key] is not None]
            y = [r[key] for r in b["repeats"] if r[key] is not None]
            if len(x) != 2 or len(y) != 2:
                continue
            improved |= max(y) + floor < min(x) * 0.95
            worsened |= min(y) > max(x) * 1.05 + floor
    global_worse = any(
        min(r[k] for r in global_after["repeats"])
        > max(r[k] for r in global_before["repeats"]) * 1.05 + before[0]["diagonal"] * 1e-6
        for k in ("p95", "p99", "regional_tail")
    ) or bool(global_after.get("warnings"))
    for key in {k for r in global_before["repeats"] for k in r.get("regions", {})}:
        x = [
            r["regions"][key]["tail"]
            for r in global_before["repeats"]
            if key in r.get("regions", {})
        ]
        y = [
            r["regions"][key]["tail"]
            for r in global_after["repeats"]
            if key in r.get("regions", {})
        ]
        if len(x) == 2 and len(y) == 2:
            global_worse |= min(y) > max(x) * 1.05 + before[0]["diagonal"] * 1e-6
    return "regression" if worsened or global_worse else "improved" if improved else "unclear"
