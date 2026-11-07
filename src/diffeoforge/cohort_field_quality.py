"""Shared material-source qualification of an unchanged final joint pilot field."""

import json
import time
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge.mesh import read_vtk_points, sha256_file, write_vtk_polydata
from diffeoforge.ordinary_field_quality import COUNTS, TEMPORAL_TOLERANCE, _surface
from diffeoforge.reference_pilot_qualification import CRITERIA

VERSION = "joint-fixed-field-quality-v1"


def qualify(run, destination, *, cancelled=lambda: False, event_callback=None):
    from diffeoforge.mesh_filter_worker import mesh_filter_cancellation

    with mesh_filter_cancellation(cancelled):
        return _qualify(Path(run), Path(destination), cancelled, event_callback)


def _qualify(run, destination, cancelled, event_callback):
    from diffeoforge.reference_fixed_shooting import movement, shoot
    from diffeoforge.reference_pca import load_reference_momenta
    from diffeoforge.reference_pca_deformations import _estimated_template_record, _safe_output_path
    from diffeoforge.source_refinement import subdivide
    from diffeoforge.surface_io import load_surface_mesh

    data = load_reference_momenta(run)
    report = data.run_report
    cfg = report.manifest["effective_config"]
    labels = list(data.subject_labels)
    actual_count = cfg["model"]["deformation"]["timepoints"]
    if (
        len(labels) < 2
        or not cfg["model"]["deformation"]["use_rk2"]
        or not 2 <= actual_count <= COUNTS[-1]
        or cfg["project"].get("parameter_provenance", {}).get("regional_fit")
        or cfg["project"].get("parameter_provenance", {}).get("finite_accepted_guard")
    ):
        raise ValueError("Joint field checks require a completed standard full-cohort RK2 field")
    template = _safe_output_path(run, _estimated_template_record(report.inventory))
    source = load_surface_mesh(template).geometry
    vertices = np.asarray(source.vertices, dtype=float).copy()
    faces = np.asarray(source.triangles, dtype=np.int64).copy()
    original_vertices = vertices.copy()
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    width = cfg["model"]["attachment"]["kernel_width"]
    if not diagonal > 0:
        raise ValueError("The final estimated material template is empty")
    inputs = {
        Path(r["staged_path"]).name: r for r in report.manifest["inputs"] if r["role"] == "subject"
    }
    if set(inputs) != set(labels):
        raise ValueError("Joint field target ordering/identity changed")
    native = {}
    bindings = {
        run / n: sha256_file(run / n)
        for n in ("manifest.json", "result.json", "output-inventory.json")
    }
    for path in (template, data.control_points_path, data.momenta_path):
        bindings[path] = sha256_file(path)
    for name, row in inputs.items():
        bindings[run / row["staged_path"]] = row["geometry"]["sha256"]
        candidates = [
            r
            for r in report.inventory
            if ("__Reconstruction__" + cfg["model"]["object_id"] + "__subject_") in r["path"]
            and r["path"].endswith("__subject_" + name + ".vtk")
        ]
        if len(candidates) != 1:
            raise ValueError("A final joint reconstruction is absent or ambiguous")
        native[name] = run / "output" / candidates[0]["path"]
        bindings[native[name]] = candidates[0]["sha256"]

    def verify():
        if any(
            p.is_symlink() or not p.is_file() or sha256_file(p) != digest
            for p, digest in bindings.items()
        ):
            raise ValueError("A bound final joint field, source, target or export changed")
        if cancelled():
            raise InterruptedError("Joint checks cancelled; completed native fit retained")

    verify()
    destination.mkdir()
    started = time.monotonic()
    before = _surface(template)
    if before["intersecting_faces"] or before["nonpositive_faces"]:
        raise ValueError("The estimated material template needs review before field qualification")
    policy = dict(
        version=VERSION,
        source_template=str(template),
        validation_timepoints=list(COUNTS),
        temporal_maximum_relative=TEMPORAL_TOLERANCE,
        maximum_source_vertices=500_000,
        maximum_source_passes=16,
        native_export_criteria={k: CRITERIA["roundtrip_" + k] for k in ("rms", "maximum")},
        optimizer_grid_criteria={
            k: CRITERIA["integration_" + k] for k in ("rms", "p95", "maximum")
        },
        bindings={str(p): h for p, h in bindings.items()},
        optimizer_updates=0,
        anatomical_approval=False,
        shared_material_grid=True,
    )
    (destination / "policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    seed = dict(
        source_run_directory=str(run),
        subject_labels=labels,
        files={
            name: dict(copy=str(path.resolve()), sha256=sha256_file(path))
            for name, path in (
                ("control_points", data.control_points_path),
                ("momenta", data.momenta_path),
            )
        },
    )
    evaluations = []

    def sample(points, count, name):
        verify()
        if event_callback:
            event_callback(
                dict(
                    event="qualification_phase",
                    message=f"Checking the saved joint field: {count} time points, "
                    f"{len(points)} material "
                    "points; no new fitting.",
                )
            )
        path = destination / (name + "-source.vtk")
        # Shooting a point cloud is evaluation of the same saved field, not an
        # optimization input or a surface-attachment replacement.
        from diffeoforge.regional_fit import _save

        _save(path, points)
        declared = dict(
            seed,
            files=dict(
                seed["files"], template=dict(copy=str(path.resolve()), sha256=sha256_file(path))
            ),
        )
        paths, protected = shoot(
            cfg,
            Path("/"),
            declared,
            destination / name,
            count,
            surface_only=cfg["model"]["object_id"],
            precision="float64",
            point_cloud=True,
            use_rk2=True,
            cancelled=cancelled,
        )
        if set(paths) != set(labels):
            raise ValueError("Joint evaluation lost a declared form")
        values = {key: np.asarray(read_vtk_points(p), dtype=float) for key, p in paths.items()}
        if any(v.shape != (len(points), 3) or not np.isfinite(v).all() for v in values.values()):
            raise ValueError("A joint fixed-field evaluation is empty, nonfinite or incomplete")
        evaluations.append(
            dict(
                name=name,
                timepoints=count,
                points=len(points),
                protected=protected,
                endpoint={k: dict(path=str(p), sha256=sha256_file(p)) for k, p in paths.items()},
            )
        )
        verify()
        return values

    def geometry(values, name, triangles):
        paths = {}
        for index, label in enumerate(labels):
            path = destination / f"{name}-{index}.vtk"
            write_vtk_polydata(path, values[label], triangles)
            paths[label] = path
        return paths

    actual = sample(vertices, actual_count, "native-grid")
    actual_paths = geometry(actual, "native-grid", faces)
    reproduction = {}
    for label in labels:
        target = load_surface_mesh(run / inputs[label]["staged_path"]).geometry
        target_diagonal = float(np.linalg.norm(np.ptp(target.vertices, axis=0)))
        if not target_diagonal > 0:
            raise ValueError("A joint target has no spatial extent")
        delta = movement(native[label], actual_paths[label], target_diagonal)
        reproduction[label] = dict(
            passed=all(delta[k] <= v for k, v in policy["native_export_criteria"].items()), **delta
        )
    if not all(r["passed"] for r in reproduction.values()):
        raise ValueError("A native joint export failed independent reproduction")
    coarse = actual if actual_count == COUNTS[0] else sample(vertices, COUNTS[0], "grid37")
    coarse_count = COUNTS[0]
    temporal = []
    temporal_passed = False
    for count in COUNTS[1:]:
        fine = sample(vertices, count, f"grid{count}")
        coarse_paths = geometry(coarse, f"coarse{coarse_count}-for{count}", faces)
        fine_paths = geometry(fine, f"grid{count}", faces)
        deltas = {s: movement(coarse_paths[s], fine_paths[s], diagonal) for s in labels}
        temporal.append(dict(coarse=coarse_count, fine=count, subjects=deltas))
        if all(r["maximum"] <= TEMPORAL_TOLERANCE for r in deltas.values()):
            temporal_passed = True
            break
        if count != COUNTS[-1]:
            coarse, coarse_count = fine, count
    final_count = count
    spatial = []
    final_paths, surfaces = {}, {}
    limited = False
    for level in range(17):
        verify()
        final_paths = geometry(fine, f"source-level{level}", faces)
        surfaces = {s: _surface(path) for s, path in final_paths.items()}
        selected = np.zeros(len(faces), dtype=bool)
        for label in labels:
            v = fine[label]
            lengths = np.max(
                np.linalg.norm(v[faces] - v[np.roll(faces, 1, axis=1)], axis=2), axis=1
            )
            selected |= lengths > width * 0.5 * (1 + 1e-8)
            if surfaces[label]["intersecting_faces"]:
                from diffeoforge.mesh_filter_worker import run_mesh_filter

                contacts = np.asarray(
                    run_mesh_filter("intersections", vertices=v, faces=faces)["faces"],
                    dtype=np.int64,
                )
                if len(contacts):
                    selected |= np.isin(faces, np.unique(faces[contacts])).any(axis=1)
        if not selected.any():
            break
        if level == 16:
            limited = True
            break
        refined, new_faces, _ = subdivide(vertices, faces, selected, maximum_vertices=500_000)
        old_count = len(vertices)
        added = sample(refined[old_count:], final_count, f"source-added{level + 1}")
        for label in labels:
            fine[label] = np.vstack((fine[label], added[label]))
        if not np.array_equal(refined[: len(original_vertices)], original_vertices):
            raise ValueError("Shared refinement changed existing estimated source vertices")
        vertices, faces = refined, new_faces
        spatial.append(
            dict(
                level=level + 1,
                old_vertices=old_count,
                new_vertices=len(vertices),
                existing_material_points_unchanged=True,
            )
        )
    # Both temporal and actual-grid checks use this exact shared refined material
    # grid. No surface repair or field-specific source mesh is substituted.
    source_path = destination / "shared-material-source.vtk"
    write_vtk_polydata(source_path, vertices, faces)
    final_coarse = sample(vertices, coarse_count, "coarse-on-shared-source")
    coarse_paths = geometry(final_coarse, "coarse-on-shared-source", faces)
    final_temporal = {s: movement(coarse_paths[s], final_paths[s], diagonal) for s in labels}
    actual_shared = sample(vertices, actual_count, "optimizer-on-shared-source")
    actual_paths = geometry(actual_shared, "optimizer-on-shared-source", faces)
    accuracy = {s: movement(actual_paths[s], final_paths[s], diagonal) for s in labels}
    rows = {}
    for label in labels:
        passed = bool(
            temporal_passed
            and not limited
            and final_temporal[label]["maximum"] <= TEMPORAL_TOLERANCE
            and not surfaces[label]["intersecting_faces"]
            and not surfaces[label]["nonpositive_faces"]
            and all(accuracy[label][k] <= v for k, v in policy["optimizer_grid_criteria"].items())
        )
        rows[label] = dict(
            version=VERSION,
            passed=passed,
            numerical_selection_suitable=passed,
            evaluation=dict(
                endpoint=dict(path=str(final_paths[label]), sha256=sha256_file(final_paths[label])),
                timepoints=final_count,
                reference_source=dict(path=str(source_path), sha256=sha256_file(source_path)),
            ),
            source_template=dict(path=str(template), sha256=sha256_file(template)),
            final_surface=surfaces[label],
            native_export_reproduction=reproduction[label],
            optimizer_grid_accuracy=accuracy[label],
            temporal_delta=final_temporal[label],
            resource_limit=limited,
            optimizer_updates=0,
            shared_material_grid=True,
            qualification_wall_seconds=time.monotonic() - started,
            anatomical_approval=False,
        )
    verify()
    result = dict(
        version=VERSION,
        passed=all(r["passed"] for r in rows.values()),
        policy=policy,
        subjects=rows,
        temporal_checks=temporal,
        spatial_checks=spatial,
        evaluations=evaluations,
        vertices=len(vertices),
        optimizer_updates=0,
        native_coefficients_unchanged=True,
        native_outputs_unchanged=True,
        qualification_wall_seconds=time.monotonic() - started,
        anatomical_approval=False,
    )
    (destination / "quality.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def evaluate_and_measure(root, candidate, run, *, cancelled, event_callback):
    directory = Path(root) / "cohort-evaluations"
    directory.mkdir(exist_ok=True)
    return qualify(
        run,
        directory / (candidate.candidate_id + "-" + uuid4().hex[:8]),
        cancelled=cancelled,
        event_callback=event_callback,
    )
