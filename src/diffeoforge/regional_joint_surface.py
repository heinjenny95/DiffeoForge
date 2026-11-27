"""Independent marked surface terms fitted by one deformation."""

import math

import numpy as np

VERSION = "joint-marked-surfaces-v1"


def supported(marks):
    return (sum(r.get("purpose", "problem") == "problem" for r in marks) >= 2
            and all(r.get("purpose", "problem") in {"problem", "fixed"}
                    and not r.get("reconstruction") and r.get("symptom") not in {"gap", "position"}
                    for r in marks))


def patches(v, f, tv, tf, regions, fixed_ids):
    from diffeoforge.regional_fit import mask
    from diffeoforge.regional_material_patch import select

    target_centres = tv[tf].mean(1)
    targets = [mask(target_centres, [region]) for region in regions]
    centres = v[f].mean(1)
    free = ~np.isin(f, fixed_ids).any(1)
    present = [mask(centres, [r]) & free for r in regions]
    # Reserve material already inside another distinct brush before inferring a
    # missing projection. Separate target patches cannot claim the same faces.
    assigned = list(present)
    result = [None] * len(regions)
    for i in sorted(range(len(regions)), key=lambda n: not present[n].any()):
        excluded = np.zeros(len(f), dtype=bool)
        for j, occupied in enumerate(assigned):
            if i != j and not (targets[i] & targets[j]).any():
                excluded |= occupied
        source, inferred = select(v, f, tv, tf, [regions[i]], fixed_ids, extend_partial=True,
                                  target_masks=[targets[i]], excluded_faces=excluded)
        assigned[i] = source
        result[i] = (source, targets[i], inferred)
    return result


def control_additions(v, f, tv, tf, marks, unresolved, points, width, limit, *, material=None):
    from diffeoforge.regional_preservation import vertex_ids

    fixed = [r for r in marks if r.get("purpose") == "fixed"]
    red = [r for r in marks if r.get("purpose", "problem") == "problem"]
    material = v if material is None else material
    parts = patches(material, f, tv, tf, red, vertex_ids(material, f, fixed) if fixed else [])
    sites = np.concatenate([np.concatenate((v[np.unique(f[src])], tv[np.unique(tf[dst])]))
                            for region, (src, dst, _) in zip(red, parts, strict=True)
                            if region in unresolved])
    origin = np.minimum(v.min(0), tv.min(0))
    for spacing in (width * .5, width * .25):
        cells = np.unique(np.floor((sites - origin) / spacing).astype(np.int64), axis=0)
        occupied = set(map(tuple, np.floor((points - origin) / spacing).astype(np.int64)))
        new = [cell for cell in cells if tuple(cell) not in occupied]
        if len(points) + len(new) > limit:
            raise ValueError("The marked source and target patches exceed the control-point limit")
        if new:
            return origin + (np.asarray(new) + .5) * spacing, spacing, dict(
                version=VERSION, marked_patches=len(unresolved), added_sites=len(new))
    raise ValueError("The existing controls already occupy the tested local cells")


def distances(v, f, tv, tf):
    """Measure both directions on the two actual patches, including a distant source."""
    from diffeoforge.reference_fit_search import grouped_surface_distances, surface_samples

    seeds = (2026103001, 2026103002)
    forward = grouped_surface_distances(
        [surface_samples(tv, tf, 2048, seed=s) for s in seeds], v, f)
    reverse = grouped_surface_distances(
        [surface_samples(v, f, 2048, seed=s) for s in seeds], tv, tf)
    repeats = [dict(original_to_fit_p95=float(np.quantile(a, .95)),
                    fit_to_original_p95=float(np.quantile(b, .95)))
               for a, b in zip(forward, reverse, strict=True)]
    if not all(math.isfinite(value) for row in repeats for value in row.values()):
        raise ValueError("Each marked surface needs finite distances in both directions")
    return repeats


def measure(original, fitted, marks):
    return measure_fields(original, fitted, marks, fitted)[0]


def measure_fields(original, material_frame, marks, *fields):
    """Compare the same moving faces at every endpoint on this evaluation grid."""
    from diffeoforge.regional_preservation import vertex_ids

    if not supported(marks):
        raise ValueError("Independent patch comparison needs multiple original-surface marks")
    v, f = np.asarray(material_frame.vertices), np.asarray(material_frame.triangles)
    tv, tf = np.asarray(original.vertices), np.asarray(original.triangles)
    fixed = [r for r in marks if r.get("purpose") == "fixed"]
    regions = [r for r in marks if r.get("purpose", "problem") == "problem"]
    parts = patches(v, f, tv, tf, regions, vertex_ids(v, f, fixed) if fixed else [])
    results = []
    for field in fields:
        endpoint = np.asarray(field.vertices)
        if endpoint.shape != v.shape or not np.array_equal(field.triangles, f):
            raise ValueError("Joint surface comparison requires the same material connectivity")
        results.append([
            dict(region=region, measurement_version=VERSION,
                 selected_faces=int(dst.sum()), reverse_selected_faces=int(src.sum()),
                 repeats=distances(endpoint, f[src], tv, tf[dst]))
            for region, (src, dst, _) in zip(regions, parts, strict=True)
        ])
    return results


def widths(measurements, nominal):
    return [max(min(nominal, row["region"]["radius"]),
                2 * max(v for repeat in row["repeats"] for v in repeat.values()))
            for row in measurements]


def prepare_objects(root, sv, sf, selection, tv, tf, regions, fixed_ids, width, noise,
                    sealed_widths):
    from diffeoforge.mesh import sha256_file
    from diffeoforge.regional_fit import _patch

    parts = list(patches(selection, sf, tv, tf, regions, fixed_ids))
    triangles = tv[tf]
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                    triangles[:, 2] - triangles[:, 0]), axis=1) * .5
    sizes = [float(areas[dst].sum()) for _, dst, _ in parts]
    if min(sizes) <= 0 or not all(map(math.isfinite, sizes)):
        raise ValueError("Each marked surface needs positive physical area")
    if sealed_widths is None:
        measurements = [dict(region=r, repeats=distances(selection, sf[src], tv, tf[dst]))
                        for r, (src, dst, _) in zip(regions, parts, strict=True)]
        sealed_widths = widths(measurements, width)
    # Varifold squared norms scale with squared surface area. Normalize each term
    # against its own target area while retaining the overall nominal weight.
    scale = sum(sizes) / math.sqrt(len(parts))
    objects, inferred = [], []
    for i, ((src, dst, inferred_rows), size, kernel) in enumerate(
            zip(parts, sizes, sealed_widths, strict=True)):
        name = "focus" if i == 0 else f"focus{i + 1}"
        obj = dict(id=name, region_index=i, kind="SurfaceMesh", kernel_width=kernel,
                   noise_std=noise * size / scale, target_area=size)
        for role, v, f, chosen in (("source", sv, sf, src), ("target", tv, tf, dst)):
            path = root / f"{name}-{role}.vtk"
            _patch(path, v, f, chosen)
            obj[role] = dict(copy=path.name, bytes=path.stat().st_size, sha256=sha256_file(path))
        inferred.extend(dict(row, region=i) for row in inferred_rows)
        objects.append(obj)
    return objects, np.logical_or.reduce([src for src, _, _ in parts]), inferred
