"""Conforming original-source refinement; never smooth or subdivide a fitted endpoint."""

from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file


def subdivide(vertices, faces, selected, *, maximum_vertices=500_000):
    """Split selected faces and conform their neighbours, retaining every old vertex."""
    v, f = np.asarray(vertices, float), np.asarray(faces, np.int64)
    selected = np.asarray(selected, bool)
    if selected.shape != (len(f),) or not np.isfinite(v).all() or f.min() < 0 or f.max() >= len(v):
        raise ValueError("Invalid original-source subdivision inputs")
    chosen = f[selected]
    edges = np.unique(
        np.sort(np.concatenate((chosen[:, [0, 1]], chosen[:, [1, 2]], chosen[:, [2, 0]])), axis=1),
        axis=0,
    )
    if len(v) + len(edges) > maximum_vertices:
        raise ValueError("Original-source refinement exceeds the declared vertex limit")
    lookup = {tuple(edge): i + len(v) for i, edge in enumerate(edges)}
    output, parents = [], []
    for index, face in enumerate(f):
        a, b, c = map(int, face)
        verts = [a, b, c]
        mids = [lookup.get(tuple(sorted(edge))) for edge in [(a, b), (b, c), (c, a)]]
        count = sum(x is not None for x in mids)
        if count == 0:
            parts = [verts]
        elif count == 3:
            ab, bc, ca = mids
            parts = [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]
        else:
            for rotation in range(3):
                vv = verts[rotation:] + verts[:rotation]
                mm = mids[rotation:] + mids[:rotation]
                if count == 1 and mm[0] is not None:
                    a, b, c = vv
                    ab = mm[0]
                    parts = [[a, ab, c], [ab, b, c]]
                    break
                if count == 2 and mm[0] is not None and mm[1] is not None:
                    a, b, c = vv
                    ab, bc = mm[:2]
                    parts = [[b, bc, ab], [a, ab, c], [ab, bc, c]]
                    break
        output.extend(parts)
        parents.extend([index] * len(parts))
    return np.vstack((v, v[edges].mean(1))), np.asarray(output, np.int64), np.asarray(parents)


def selection(vertices, faces, regions, width, *, source_vertices=None):
    from diffeoforge.mesh_filter_worker import run_mesh_filter
    from diffeoforge.regional_fit import mask

    v, f = np.asarray(vertices, float), np.asarray(faces, np.int64)
    active = mask(v[f].mean(1), regions, halo=width)
    lengths = np.max(np.linalg.norm(v[f] - v[np.roll(f, 1, axis=1)], axis=2), axis=1)
    selected = active & (lengths > width * 0.5 * (1 + 1e-8))
    flagged = run_mesh_filter("intersections", vertices=v, faces=f)["faces"]
    # Straight triangles can cross even when the ambient field is smooth. Chase
    # new contacts across the whole surface, including just outside the focus.
    # Existing source contacts cannot be repaired by evaluating this same map.
    seeds = np.asarray(flagged, dtype=np.int64)
    if source_vertices is not None:
        original = np.asarray(source_vertices, float)
        if original.shape != v.shape or not np.isfinite(original).all():
            raise ValueError("Contact refinement needs the matching original material grid")
        preexisting = run_mesh_filter("intersections", vertices=original, faces=f)["faces"]
        seeds = np.setdiff1d(seeds, preexisting)
    if len(seeds):
        selected |= np.isin(f, np.unique(f[seeds])).any(1)
    return selected


def augment(receipt, points_receipt, grid, faces, directory):
    """Combine independent material-point batches of the same unchanged fields."""
    from diffeoforge.mesh import read_vtk_points, read_vtk_polydata
    from diffeoforge.regional_fit import _save

    if any(
        receipt[k] != points_receipt[k]
        for k in ("source_run", "timepoints", "controls_sha256", "momenta_sha256")
    ):
        raise ValueError("Incremental evaluation uses different fitted fields")
    grid = Path(grid)
    from diffeoforge.surface_io import load_surface_mesh

    reference = load_surface_mesh(grid).geometry
    old_source = receipt.get("reference_source")
    if old_source:
        path = Path(old_source["path"])
        if sha256_file(path) != old_source["sha256"]:
            raise ValueError("Cached original source changed")
        previous = load_surface_mesh(path).geometry
        if not np.array_equal(reference.vertices[: len(previous.vertices)], previous.vertices):
            raise ValueError("Refinement changed existing original material points")
    directory = Path(directory)
    directory.mkdir()
    result = dict(receipt)
    if receipt["prefix"]:
        result["prefix"] = augment(
            receipt["prefix"], points_receipt["prefix"], grid, faces, directory / "prefix"
        )
    before, added = Path(receipt["endpoint"]["path"]), Path(points_receipt["endpoint"]["path"])
    if (
        sha256_file(before) != receipt["endpoint"]["sha256"]
        or sha256_file(added) != points_receipt["endpoint"]["sha256"]
    ):
        raise ValueError("Cached or new-point field endpoint changed")
    old = read_vtk_polydata(before)
    vertices = np.vstack((old.vertices, read_vtk_points(added)))
    if len(vertices) != len(reference.vertices):
        raise ValueError("New-point evaluation does not cover the refined original grid")
    endpoint = directory / "endpoint.vtk"
    _save(endpoint, vertices, faces)
    result.update(
        endpoint=dict(path=str(endpoint), sha256=sha256_file(endpoint)),
        reference_source=dict(path=str(Path(grid).resolve()), sha256=sha256_file(Path(grid))),
        incremental_evaluation=dict(
            old_endpoint=receipt["endpoint"],
            new_points=points_receipt,
            old_vertices=len(old.vertices),
            new_vertices=len(vertices) - len(old.vertices),
            purpose="Same ambient fields on new original points; no endpoint mesh interpolation",
        ),
    )
    result["source_template_sha256"] = (
        result["prefix"]["endpoint"]["sha256"] if result["prefix"] else sha256_file(grid)
    )
    return result


def refine_evaluation(run, receipt, destination, plan, *, cancelled, event_callback, cache=None):
    """Refine the reference surface, then replay all unchanged fields from it."""
    from diffeoforge.regional_evaluation import evaluate_points
    from diffeoforge.regional_fit import _save
    from diffeoforge.surface_io import load_surface_mesh

    # Congruent-part spacing qualification retains its declared original grid.
    if plan["guidance"]:
        return receipt
    root = Path(destination)
    root.mkdir()
    obj = next(r for r in plan["objects"] if r["id"] == "focus")
    width = obj["kernel_width"]
    stages, limited = [], False
    for level in range(8):
        source = load_surface_mesh(receipt["reference_source"]["path"]).geometry
        fitted = load_surface_mesh(receipt["endpoint"]["path"]).geometry
        v, f = np.asarray(source.vertices), np.asarray(source.triangles)
        if not np.array_equal(f, fitted.triangles) or len(v) != len(fitted.vertices):
            raise ValueError("Original reference and fitted grid differ")
        selected = selection(fitted.vertices, f, plan["focus_regions"], width,
                             source_vertices=v)
        if not selected.any():
            break
        if cancelled():
            raise InterruptedError("Original-source evaluation cancelled; fitted fields retained")
        if event_callback:
            event_callback(
                dict(
                    event="qualification_phase",
                    message=(f"Refining the original source, pass {level + 1}; "
                             "fitted fields stay unchanged."),
                )
            )
        try:
            refined, faces, parents = subdivide(v, f, selected)
        except ValueError as error:
            if "vertex limit" not in str(error):
                raise
            limited = True
            break
        folder = root / f"level-{level + 1}"
        folder.mkdir()
        grid = folder / "original-source-grid.vtk"
        _save(grid, refined, faces)
        np.save(folder / "parent-faces.npy", parents)
        before = receipt
        added = evaluate_points(
            run,
            refined[len(v) :],
            folder / "new-material-points",
            count=receipt["timepoints"],
            cancelled=cancelled,
            event_callback=event_callback,
            _cache=cache,
        )
        receipt = augment(receipt, added, grid, faces, folder / "full-composition")
        stages.append(
            dict(
                original_vertices=len(v),
                refined_vertices=len(refined),
                selected_faces=int(selected.sum()),
                source_sha256=before["reference_source"]["sha256"],
                grid_sha256=sha256_file(grid),
                parent_faces_sha256=sha256_file(folder / "parent-faces.npy"),
                old_vertices_identical=bool(np.array_equal(refined[: len(v)], v)),
                source_surface_unchanged=True,
            )
        )
    else:
        source = load_surface_mesh(receipt["reference_source"]["path"]).geometry
        fitted = load_surface_mesh(receipt["endpoint"]["path"]).geometry
        limited = bool(selection(fitted.vertices, fitted.triangles,
                                 plan["focus_regions"], width,
                                 source_vertices=source.vertices).any())
    receipt["source_refinement"] = dict(
        stages=stages,
        resource_limit=limited,
        maximum_vertices=500_000,
        maximum_passes=8,
        method="Conforming linear subdivision before original-source full-chain evaluation",
    )
    return receipt
