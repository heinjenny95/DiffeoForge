"""Regional, transition and preservation checks; no automatic anatomy decision."""

import json
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.regional_fit import _components, mask, read_plan
from diffeoforge.regional_frame import TEMPORAL_COUNTS, TEMPORAL_TOLERANCE


def _distances(target, target_faces, fitted, fitted_faces, areas):
    from diffeoforge.reference_fit_search import distances_to_surface, surface_samples

    rows = []
    a = target_faces[mask(target[target_faces].mean(1), areas)]
    b = fitted_faces[mask(fitted[fitted_faces].mean(1), areas)]
    if not len(a):
        raise ValueError("Regional surface verification needs faces in the marked original")
    if not len(b):
        # A genuinely missing tip may not reach the marked target region yet.
        # Measure the closest fitted face too; do not lose the completed trial.
        centre = target[a].mean(axis=(0, 1))
        nearest = np.argmin(np.linalg.norm(fitted[fitted_faces].mean(1) - centre, axis=1))
        b = fitted_faces[[nearest]]
    for seed in (2026102901, 2026102902):
        x = distances_to_surface(surface_samples(target, a, 2048, seed=seed), fitted, fitted_faces)
        y = distances_to_surface(surface_samples(fitted, b, 2048, seed=seed), target, target_faces)
        rows.append(
            dict(
                original_to_fit_mean=float(x.mean()),
                original_to_fit_p95=float(np.quantile(x, 0.95)),
                fit_to_original_mean=float(y.mean()),
                fit_to_original_p95=float(np.quantile(y, 0.95)),
            )
        )
    return rows


def measure(config, fitted_path, *, source_path=None, baseline_path=None):
    from diffeoforge.surface_io import load_surface_mesh

    plan = read_plan(config)
    source = load_surface_mesh(config["input"]["template"]).geometry
    if plan.get("residual"):
        directory = Path(config["project"]["parameter_provenance"]["regional_fit"]["manifest"])
        source = load_surface_mesh(directory.parent / plan["residual"]["source"]["copy"]).geometry
    if source_path is not None:
        source = load_surface_mesh(source_path).geometry
    target_path = Path(config["input"]["directory"]) / plan.get("target_filename", "")
    if not target_path.is_file():
        choices = [
            p
            for p in Path(config["input"]["directory"]).glob(config["input"]["subject_pattern"])
            if sha256_file(p) == plan["target_sha256"]
        ]
        if len(choices) != 1:
            raise ValueError("The regional original target is missing or ambiguous")
        target_path = choices[0]
    target = load_surface_mesh(target_path).geometry
    fitted = load_surface_mesh(fitted_path).geometry
    sv, sf = np.asarray(source.vertices, float), np.asarray(source.triangles, int)
    tv, tf = np.asarray(target.vertices, float), np.asarray(target.triangles, int)
    fv, ff = np.asarray(fitted.vertices, float), np.asarray(fitted.triangles, int)
    if sf.shape != ff.shape or not np.array_equal(sf, ff) or sv.shape != fv.shape:
        raise ValueError("Regional verification requires full, unchanged source connectivity")
    diagonal = float(np.linalg.norm(np.ptp(tv, axis=0)))
    current = _distances(tv, tf, fv, ff, plan["focus_regions"])
    before = None
    retained = plan.get("retained_reference")
    if retained:
        if sha256_file(Path(retained["path"])) != retained["sha256"]:
            raise ValueError("The retained comparison changed")
        original = load_surface_mesh(baseline_path or retained["path"]).geometry
        before = _distances(
            tv,
            tf,
            np.asarray(original.vertices, float),
            np.asarray(original.triangles, int),
            plan["focus_regions"],
        )
    p95 = max(max(r["original_to_fit_p95"], r["fit_to_original_p95"]) for r in current)
    old_p95 = (
        max(max(r["original_to_fit_p95"], r["fit_to_original_p95"]) for r in before)
        if before
        else None
    )
    transitions = old_p95 is None or p95 <= max(old_p95 * 1.05, diagonal * 1e-4)
    ids = plan.get("protection_vertex_ids")
    if ids is None:
        # Legacy generated plans have the same protected vertex coordinates.
        from diffeoforge.mesh import read_vtk_points

        obj = next(x for x in plan["objects"] if x["id"] == "protect")
        path = Path(config["project"]["parameter_provenance"]["regional_fit"]["manifest"])
        coords = np.asarray(read_vtk_points(path.parent / obj["source"]["copy"]), float)
        index = {tuple(v): i for i, v in enumerate(sv)}
        ids = [index[tuple(v)] for v in coords]
    protection = next(x for x in plan["objects"] if x["id"] == "protect")
    from diffeoforge.mesh import read_vtk_points

    root = Path(config["project"]["parameter_provenance"]["regional_fit"]["manifest"]).parent
    expected = np.asarray(read_vtk_points(root / protection["target"]["copy"]), float)
    displacement = np.linalg.norm(fv[ids] - expected, axis=1)
    position_limit = plan.get('protection_tolerance') or diagonal*1e-4
    outside = float(np.quantile(displacement, 0.95)) <= position_limit
    fixed_ids = plan.get('fixed_vertex_ids', [])
    fixed_positions = {identifier: index for index, identifier in enumerate(ids)}
    fixed_preserved = all(displacement[fixed_positions[i]] <= diagonal*1e-4 for i in fixed_ids)
    preserved_surface = []
    if plan.get('protection_close_distance') and retained:
        from diffeoforge.reference_fit_search import distances_to_surface, surface_samples

        ov, of = np.asarray(original.vertices, float), np.asarray(original.triangles, int)
        for seed in (2026102903, 2026102904):
            points = surface_samples(tv, tf, 8192, seed=seed)
            points = points[~mask(points, plan['focus_regions'], halo=plan['protection_halo'])]
            old = distances_to_surface(points, ov, of)
            keep = old <= plan['protection_close_distance']
            if not keep.any():
                continue
            new = distances_to_surface(points[keep], fv, ff)
            before_p95, after_p95 = float(np.quantile(old[keep], .95)), float(np.quantile(new, .95))
            preserved_surface.append(dict(points=int(keep.sum()), before_p95=before_p95,
                after_p95=after_p95, bound=before_p95+position_limit,
                passed=after_p95 <= before_p95+position_limit))
        # Automatic confidence anchors are soft regularization of a surface,
        # not anatomical/material correspondences. Tangential remapping can
        # preserve the exact surface while moving its parameterization. Only
        # explicit fixed marks retain the strict material-position gate below.
        outside = bool(preserved_surface) and all(r['passed'] for r in preserved_surface)
    outside &= fixed_preserved
    shape_rows = []
    if plan["guidance"]:
        for item in _components(sv, sf[mask(sv[sf].mean(1), plan["regions"])]):
            faces = item["faces"]
            indices = np.unique(faces)
            a, b = sv[indices], fv[indices]
            ac, bc = a - a.mean(0), b - b.mean(0)
            u, _, vt = np.linalg.svd(bc.T @ ac)
            rotation = u @ vt
            if np.linalg.det(rotation) < 0:
                u[:, -1] *= -1
                rotation = u @ vt
            extent = max(float(np.linalg.norm(np.ptp(a, axis=0))), 1e-15)
            t = fv[faces]
            area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()
            shape_rows.append(
                dict(
                    area_change=abs(float(area) / item["area"] - 1),
                    rigid_rms=float(np.sqrt(np.mean(np.sum((bc @ rotation - ac) ** 2, axis=1))))
                    / extent,
                )
            )
    preserved = all(r["area_change"] <= 0.01 and r["rigid_rms"] <= 0.005 for r in shape_rows)
    from diffeoforge.mesh_filter_worker import run_mesh_filter

    before_flags = run_mesh_filter("intersections", vertices=sv, faces=sf)["faces"]
    after_flags = run_mesh_filter("intersections", vertices=fv, faces=ff)["faces"]
    new_flags = np.setdiff1d(after_flags, before_flags)
    local_improved = (
        before is not None
        and max(r["original_to_fit_mean"] for r in current)
        < min(r["original_to_fit_mean"] for r in before) * 0.95
    )
    return dict(
        version="regional-quality-v1",
        active_surface=current,
        baseline_surface=before,
        active_surface_p95=p95,
        baseline_surface_p95=old_p95,
        transition_preserved=bool(transitions),
        outside_preserved=bool(outside),
        outside_displacement_p95=float(np.quantile(displacement, 0.95)),
        outside_displacement_max=float(displacement.max()),
        outside_position_limit=position_limit,
        unmarked_preservation_basis=('original_surface' if preserved_surface else
                                     'material_positions'),
        explicit_fixed_preserved=bool(fixed_preserved),
        previously_good_surface=preserved_surface,
        marked_regions=plan['focus_regions'],
        shape=shape_rows,
        shape_preserved=bool(preserved),
        no_new_intersection_flags=not len(new_flags),
        preexisting_intersection_flags=before_flags.tolist(),
        new_intersection_flags=new_flags.tolist(),
        local_improved=bool(local_improved),
        requires_visual_review=True,
        anatomical_approval=False,
        numerical_selection_suitable=bool(
            transitions and outside and preserved and not len(new_flags)
        ),
        limitation="Finite surface/patch-shape tests, not full section, homology or path proof",
    )


def evaluate_and_measure(
    root, manifest, candidate, run, *, cancelled=lambda: False, event_callback=None
):
    from diffeoforge.config import load_config
    from diffeoforge.regional_evaluation import evaluate

    record = manifest["attachment_comparison"]
    if not record.get("regional_objective"):
        return None
    from uuid import uuid4

    destination = (
        Path(root) / "regional-evaluations" / (candidate.candidate_id + "-" + uuid4().hex[:8])
    )
    cache = {}
    receipt = evaluate(
        run, destination, cancelled=cancelled, event_callback=event_callback, _cache=cache
    )
    config = load_config(candidate.config_path)
    from diffeoforge.config import validate_input_paths

    summary = validate_input_paths(config, candidate.config_path)
    config["input"].update(template=str(summary.template), directory=str(summary.input_directory))
    from diffeoforge.source_refinement import refine_evaluation

    plan = read_plan(config)
    grid = Path(receipt["reference_source"]["path"])
    from diffeoforge.reference_fixed_shooting import movement
    from diffeoforge.surface_io import load_surface_mesh

    vertices = np.asarray(load_surface_mesh(summary.template).geometry.vertices, float)
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    coarse = evaluate(
        run,
        destination.with_name(destination.name + "-grid37"),
        count=37,
        _source=grid,
        cancelled=cancelled,
        event_callback=event_callback,
        _cache=cache,
    )
    comparisons = []
    for count in TEMPORAL_COUNTS:
        if count != 73:
            coarse = receipt
            receipt = evaluate(
                run,
                destination.with_name(destination.name + f"-grid{count}"),
                count=count,
                _source=grid,
                cancelled=cancelled,
                event_callback=event_callback,
                _cache=cache,
            )
        delta = movement(
            Path(coarse["endpoint"]["path"]), Path(receipt["endpoint"]["path"]), diagonal
        )
        comparisons.append(dict(coarse=coarse["timepoints"], fine=count, **delta))
        if delta["maximum"] <= TEMPORAL_TOLERANCE:
            break
    receipt = refine_evaluation(
        run,
        receipt,
        destination.with_name(destination.name + "-spatial"),
        plan,
        cancelled=cancelled,
        event_callback=event_callback,
        cache=cache,
    )
    refinement = receipt.get("source_refinement")
    final_grid = Path(receipt["reference_source"]["path"])
    if sha256_file(final_grid) != sha256_file(grid):
        coarse_count = comparisons[-1]["coarse"]
        coarse = evaluate(
            run,
            destination.with_name(destination.name + "-spatial-grid-check"),
            count=coarse_count,
            _source=final_grid,
            cancelled=cancelled,
            event_callback=event_callback,
            _cache=cache,
        )
        delta = movement(
            Path(coarse["endpoint"]["path"]), Path(receipt["endpoint"]["path"]), diagonal
        )
        comparisons.append(dict(coarse=coarse_count, fine=receipt["timepoints"], **delta))
        while (comparisons[-1]["maximum"] > TEMPORAL_TOLERANCE
               and receipt["timepoints"] < TEMPORAL_COUNTS[-1]):
            coarse = receipt
            count = receipt["timepoints"] * 2 - 1
            receipt = evaluate(
                run,
                destination.with_name(destination.name + f"-spatial-t{count}"),
                count=count,
                _source=final_grid,
                cancelled=cancelled,
                event_callback=event_callback,
                _cache=cache,
            )
            delta = movement(
                Path(coarse["endpoint"]["path"]), Path(receipt["endpoint"]["path"]), diagonal
            )
            comparisons.append(dict(coarse=coarse["timepoints"], fine=count, **delta))
    grid = final_grid
    baseline = None
    if plan.get("retained_run"):
        parent = plan["retained_run"]
        if sha256_file(Path(parent["path"]) / "manifest.json") != parent["manifest_sha256"]:
            raise ValueError("Retained comparison run changed")
        baseline = evaluate(
            parent["path"],
            destination.with_name(destination.name + "-baseline"),
            count=receipt["timepoints"],
            _source=grid,
            cancelled=cancelled,
            event_callback=event_callback,
            _cache=cache,
        )
    source = receipt["prefix"]["endpoint"]["path"] if receipt["prefix"] else str(grid)
    quality = measure(
        config,
        receipt["endpoint"]["path"],
        source_path=source,
        baseline_path=baseline["endpoint"]["path"] if baseline else None,
    )
    if baseline:
        quality["baseline_evaluation"] = baseline
    if refinement:
        receipt["source_refinement"] = refinement
    quality["spatial_resolution_sufficient"] = not (refinement or {}).get("resource_limit", False)
    quality["temporal_grid_checks"] = comparisons
    quality["temporal_grid_stable"] = comparisons[-1]["maximum"] <= TEMPORAL_TOLERANCE
    receipt["starting_frame_qualification"] = dict(
        temporal_stable=quality["temporal_grid_stable"], temporal_checks=comparisons,
        optimizer_updates=0, purpose="Dense original-source composed RK2 evaluation")
    quality["numerical_selection_suitable"] &= quality["temporal_grid_stable"]
    quality["numerical_selection_suitable"] &= quality["spatial_resolution_sufficient"]
    quality["evaluation"] = receipt
    path = destination / "quality.json"
    path.write_text(json.dumps(quality, indent=2) + "\n")
    return quality
