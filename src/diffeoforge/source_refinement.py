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
    if not len(edges):
        return v.copy(), f.copy(), np.arange(len(f), dtype=np.int64)
    from diffeoforge._conforming_children import children

    output, parents = children(f, edges, len(v))
    return np.vstack((v, v[edges].mean(1))), output, parents


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
    # A caller may exempt genuine original-input contacts. A discretized prefix
    # of a clean original input can itself need denser material evaluation.
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


def _selection(receipt, source, fitted, regions, width, *, coarse_input_clean=False):
    from diffeoforge.surface_io import load_surface_mesh

    # QC compares a residual with its incoming (prefix) surface. The original
    # material grid remains the subdivision domain, not this contact baseline.
    before = (load_surface_mesh(receipt['prefix']['endpoint']['path']).geometry
              if receipt.get('prefix') else source)
    if not np.array_equal(before.triangles, fitted.triangles):
        raise ValueError('Incoming field and fitted contact grids differ')
    return selection(fitted.vertices, fitted.triangles, regions, width,
                     source_vertices=None if coarse_input_clean else before.vertices)


def coarse_input_contacts(receipt, cache=None):
    """Inspect the verified coarse input, not its roundoff-sensitive subdivision."""
    from diffeoforge.mesh_filter_worker import run_mesh_filter
    from diffeoforge.regional_evaluation import field_inputs
    from diffeoforge.surface_io import load_surface_mesh

    seen = set()
    while receipt.get('prefix'):
        key = receipt['source_run']
        if key in seen or len(seen) >= 12:
            raise ValueError('Cyclic or excessive original material source chain')
        seen.add(key)
        receipt = receipt['prefix']
    run = Path(receipt['source_run'])
    data = field_inputs(run, cache)
    row = next(r for r in data.run_report.manifest['inputs'] if r['role'] == 'template')
    path = run / row['staged_path']
    mesh = load_surface_mesh(path).geometry
    count = len(run_mesh_filter('intersections', vertices=mesh.vertices,
                                faces=mesh.triangles)['faces'])
    return dict(path=str(path), sha256=sha256_file(path), flagged_faces=count, clean=count == 0)


def augment(receipt, points_receipt, grid, faces, directory):
    """Combine independent material-point batches of the same unchanged fields."""
    from diffeoforge._refinement_grid_cache import _OriginalGridCache
    from diffeoforge.surface_io import load_surface_mesh

    with _OriginalGridCache(load_surface_mesh) as grids:
        return _augment(receipt, points_receipt, grid, faces, directory, grids)


def _augment(receipt, points_receipt, grid, faces, directory, grids):
    """Share verified original grids only within the outer augmentation call."""
    from diffeoforge.mesh import read_vtk_points, read_vtk_polydata
    from diffeoforge.regional_fit import _save

    if any(
        receipt[k] != points_receipt[k]
        for k in ("source_run", "timepoints", "controls_sha256", "momenta_sha256")
    ):
        raise ValueError("Incremental evaluation uses different fitted fields")
    grid = Path(grid)
    reference = grids.get(grid)
    old_source = receipt.get("reference_source")
    if old_source:
        path = Path(old_source["path"])
        if sha256_file(path) != old_source["sha256"]:
            raise ValueError("Cached original source changed")
        previous = grids.get(path)
        if not np.array_equal(reference.vertices[: len(previous.vertices)], previous.vertices):
            raise ValueError("Refinement changed existing original material points")
    directory = Path(directory)
    directory.mkdir()
    result = dict(receipt)
    if receipt["prefix"]:
        result["prefix"] = _augment(
            receipt["prefix"], points_receipt["prefix"], grid, faces, directory / "prefix", grids
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
    original_contacts = coarse_input_contacts(receipt, cache)
    maximum_passes = 16 if original_contacts['clean'] else 8
    stages, limited = [], False
    for level in range(maximum_passes):
        source = load_surface_mesh(receipt["reference_source"]["path"]).geometry
        fitted = load_surface_mesh(receipt["endpoint"]["path"]).geometry
        v, f = np.asarray(source.vertices), np.asarray(source.triangles)
        if not np.array_equal(f, fitted.triangles) or len(v) != len(fitted.vertices):
            raise ValueError("Original reference and fitted grid differ")
        selected = _selection(receipt, source, fitted, plan['focus_regions'], width,
                              coarse_input_clean=original_contacts['clean'])
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
        limited = bool(_selection(receipt, source, fitted, plan['focus_regions'], width,
                                 coarse_input_clean=original_contacts['clean']).any())
    receipt["source_refinement"] = dict(
        stages=stages,
        resource_limit=limited,
        maximum_vertices=500_000,
        maximum_passes=maximum_passes,
        original_coarse_contact_status=original_contacts,
        inherited_contacts_refined=original_contacts['clean'],
        method="Conforming linear subdivision before original-source full-chain evaluation",
    )
    return receipt
