"""Source-bound 3D feedback, explicit regional trial intent and measurements."""

from __future__ import annotations

import math

import numpy as np

VERSION = "surface-region-v1"
EDIT_VERSION = "surface-region-v2"
BOX_VERSION = "surface-box-v1"
SYMPTOMS = {
    "detail": "Details are missing",
    "missing": "Part of the surface is missed",
    "shape": "The shape or position is wrong",
    "distortion": "The reconstruction looks distorted",
    "thickness": "This part is too thick or too thin",
    "position": "The part has the wrong position; its shape is otherwise good",
    "curvature": "The bending or curvature is wrong",
    "gap": "The gap or spacing is wrong; preserve the adjacent parts",
    "alignment": "The overall alignment is wrong",
    "topology": "A surface is merged, disconnected, or has a different opening",
    "view": "I cannot judge the view or displayed detail",
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
            expected = {
                "version",
                "source_sha256",
                "space",
                "center",
                "radius",
                "symptom",
            }
            boxed = isinstance(row, dict) and row.get("version") == BOX_VERSION
            if isinstance(row, dict) and row.get("version") in {EDIT_VERSION, BOX_VERSION}:
                expected |= {"purpose"} if "purpose" in row else set()
            if boxed:
                expected |= {"shape", "bounds"}
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError("Invalid 3D region record")
            center, radius = row["center"], row["radius"]
            if (
                row["version"] not in {VERSION, EDIT_VERSION, BOX_VERSION}
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
            if row.get("purpose", "problem") not in {"problem", "preserve", "fixed"}:
                raise ValueError("Choose whether to improve, preserve shape, or keep an area fixed")
            if boxed:
                bounds = row["bounds"]
                if (row["shape"] != "box" or not isinstance(bounds, (list, tuple))
                        or len(bounds) != 6 or any(type(x) not in (int, float)
                        or not math.isfinite(x) for x in bounds)
                        or any(bounds[i] >= bounds[i + 1] for i in (0, 2, 4))):
                    raise ValueError("Invalid three-dimensional box")
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
    from diffeoforge.reference_fit_search import grouped_surface_distances, surface_samples

    if not regions:
        return []
    av, af = np.asarray(original.vertices, float), np.asarray(original.triangles, int)
    bv, bf = np.asarray(reconstruction.vertices, float), np.asarray(reconstruction.triangles, int)
    diagonal = float(np.linalg.norm(np.ptp(av, axis=0)))
    result = []
    seeds = (20261022, 20261023)
    reverse_samples = {seed: surface_samples(bv, bf, 8192, seed=seed) for seed in seeds}
    forward_groups, reverse_groups = [], []
    for row in regions:
        from diffeoforge.regional_fit import mask as region_mask

        chosen = region_mask(av[af].mean(1), [row])
        if not chosen.any():
            raise ValueError("The marked brush contains no original face centres; enlarge it")
        repeats = []
        for seed in seeds:
            points = surface_samples(av, af[chosen], 2048, seed=seed)
            reverse = reverse_samples[seed]
            reverse = reverse[region_mask(reverse, [row])]
            forward_groups.append(points)
            reverse_groups.append(reverse)
            repeats.append(
                dict(
                    reverse_count=len(reverse),
                )
            )
        result.append(
            dict(region=row, selected_faces=int(chosen.sum()), diagonal=diagonal, repeats=repeats)
        )
    forward = grouped_surface_distances(forward_groups, bv, bf)
    reverse = grouped_surface_distances(reverse_groups, av, af)
    repeats = [repeat for row in result for repeat in row["repeats"]]
    for repeat, distances, back in zip(repeats, forward, reverse, strict=True):
        repeat.update(
            original_to_fit_p95=float(np.quantile(distances, 0.95)),
            original_to_fit_mean=float(np.mean(distances)),
            original_to_fit_p99=float(np.quantile(distances, 0.99)),
            fit_to_original_p95=float(np.quantile(back, 0.95)) if len(back) else None,
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
