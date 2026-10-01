"""Time-bounded pilot screening against originals, followed by full-target fitting.

Working meshes are scientific approximation inputs, never display proxies. The
template retains its complete topology. No fit score can approve anatomy.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge.config import load_config, validate_schema
from diffeoforge.mesh import sha256_file, write_vtk_polydata
from diffeoforge.reference_calibration import CalibrationCandidate, _canonical_hash
from diffeoforge.surface_io import load_surface_mesh

VERSION = "surface-fit-search-v1"
TARGET_FACES = 20_000
SAMPLES = 2048


def surface_samples(vertices, faces, count=SAMPLES):
    """Fixed-seed equal-area samples; independent of source vertex density."""
    v, f = np.asarray(vertices, float), np.asarray(faces, int)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    areas = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if not np.isfinite(areas).all() or not areas.sum() > 0:
        raise ValueError("Surface sampling needs finite positive area")
    # Stratified area selection avoids randomly missing entire large faces.
    rng = np.random.default_rng(20261001)
    idx = np.searchsorted(np.cumsum(areas), (np.arange(count) + 0.5) * areas.sum() / count)
    u, w = rng.random((2, count))
    u = np.sqrt(u)
    return (1 - u[:, None]) * a[idx] + (u * (1 - w))[:, None] * b[idx] + (u * w)[:, None] * c[idx]


def distances_to_surface(points, vertices, faces):
    """Unsigned sampled point-to-triangle distance using MeshLab's spatial index."""
    import pymeshlab as pm

    ms = pm.MeshSet()
    ms.add_mesh(
        pm.Mesh(vertex_matrix=np.asarray(vertices, float), face_matrix=np.asarray(faces, np.int32))
    )
    ms.add_mesh(pm.Mesh(vertex_matrix=np.asarray(points, float)))
    combined = np.concatenate((np.asarray(points, float), np.asarray(vertices, float)))
    distance_limit = float(np.linalg.norm(np.ptp(combined, axis=0))) * 2 + 1e-12
    ms.apply_filter(
        "compute_scalar_by_distance_from_another_mesh_per_vertex",
        measuremesh=1,
        refmesh=0,
        signeddist=False,
        maxdist=pm.PureValue(distance_limit),
    )
    values = np.asarray(ms.mesh(1).vertex_scalar_array(), float).copy()
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Nonfinite surface distances")
    return values


def surface_fit(first, second):
    av, af = first.vertices, first.triangles
    bv, bf = second.vertices, second.triangles
    directions = [
        distances_to_surface(surface_samples(av, af), bv, bf),
        distances_to_surface(surface_samples(bv, bf), av, af),
    ]
    diagonal = float(np.linalg.norm(np.ptp(np.asarray(av), axis=0)))
    if not diagonal > 0:
        raise ValueError("Original surface has no spatial extent")
    return {
        "p95": max(float(np.quantile(d, 0.95)) for d in directions),
        "p99": max(float(np.quantile(d, 0.99)) for d in directions),
        "mean": max(float(np.mean(d)) for d in directions),
        "diagonal": diagonal,
    }


def control_grid(bounds, target=200):
    lo, hi = np.asarray(bounds)[::2], np.asarray(bounds)[1::2]
    span = hi - lo
    if not np.isfinite(span).all() or not span.max() > 0:
        raise ValueError("Control grid requires nonzero finite bounds")
    spacing = float(span.max()) / 6
    for _ in range(80):
        shape = np.maximum(3, np.ceil(span / spacing).astype(int) + 1)
        if np.prod(shape) <= target:
            break
        spacing *= 1.08
    axes = [
        np.linspace(a, b, int(n)) if b > a else np.linspace(a - spacing, a + spacing, int(n))
        for a, b, n in zip(lo, hi, shape, strict=True)
    ]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return grid, spacing


def prepare_working_targets(root, manifest, search):
    import pymeshlab as pm

    records = []
    for row in manifest["inputs"]["subjects"]:
        source = root / row["copy"]
        loaded = load_surface_mesh(source)
        ms = pm.MeshSet()
        ms.add_mesh(
            pm.Mesh(
                vertex_matrix=np.asarray(loaded.geometry.vertices, float),
                face_matrix=np.asarray(loaded.geometry.triangles, np.int32),
            )
        )
        if ms.current_mesh().face_number() > TARGET_FACES:
            ms.apply_filter(
                "meshing_decimation_quadric_edge_collapse",
                targetfacenum=TARGET_FACES,
                preservetopology=True,
                preservenormal=True,
                preserveboundary=True,
            )
        mesh = ms.current_mesh()
        if mesh.face_number() > TARGET_FACES * 1.5:
            raise ValueError("Topology-preserving working mesh exceeds the screening budget")
        dst = root / "working-targets" / row["filename"]
        dst.parent.mkdir(exist_ok=True)
        write_vtk_polydata(
            dst,
            mesh.vertex_matrix(),
            mesh.face_matrix(),
            title="DiffeoForge scientific screening target",
        )
        records.append(
            dict(
                filename=row["filename"],
                copy=dst.relative_to(root).as_posix(),
                sha256=sha256_file(dst),
                source_sha256=row["sha256"],
                faces=mesh.face_number(),
            )
        )
    template = load_surface_mesh(root / manifest["inputs"]["template"]["copy"])
    controls, spacing = control_grid(template.metadata.bounds)
    dst = root / "search-controls.txt"
    np.savetxt(dst, controls, fmt="%.17g")
    search.update(
        version=VERSION,
        working_targets=records,
        spacing=spacing,
        controls=dict(copy=dst.name, sha256=sha256_file(dst), count=len(controls)),
        confirmation_ids=[],
        budget_directory=str(root),
    )
    return search


def verify_search(root, manifest):
    search = manifest["fit_search"]
    if search.get("version") != VERSION:
        raise ValueError("Unknown scientific screening protocol")
    from diffeoforge import reference_calibration_study as study

    if Path(search["budget_directory"]).resolve() != study._search_extension_series(root)[0]:
        raise ValueError("Fit-search budget is not bound to its original series")
    originals = {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]}
    if {r["filename"]: r["source_sha256"] for r in search["working_targets"]} != originals:
        raise ValueError("Working targets do not cover the complete original pilot cohort")
    for row in [*search["working_targets"], search["controls"]]:
        path = (root / row["copy"]).resolve()
        if not path.is_relative_to(root.resolve()) or sha256_file(path) != row["sha256"]:
            raise ValueError("Scientific working geometry changed")


def inherit_search(source, root, manifest, proposal, confirm):
    from diffeoforge import reference_calibration_study as study

    verify_search(source, manifest)
    search = copy.deepcopy(manifest["fit_search"])
    for row in [*search["working_targets"], search["controls"]]:
        study._copy_bound(source / row["copy"], root / row["copy"], row["sha256"])
    if confirm:
        search["confirmation_ids"].extend(c.candidate_id for c in proposal.candidates)
    return search


def configure_trial(config, root, directory, manifest, candidate_id):
    search = manifest["fit_search"]
    # Subsequent ordinary pilot stages use original inputs and the existing workflow.
    current_ids = {r["candidate_id"] for r in manifest["plan"]["stages"][0]["candidates"]}
    if candidate_id not in current_ids:
        return
    if candidate_id not in search["confirmation_ids"]:
        config["input"]["directory"] = os.path.relpath(root / "working-targets", directory)
        config["optimization"]["freeze_template"] = True
        config["optimization"]["freeze_control_points"] = True
    else:
        config["optimization"].update(search["confirmation_freeze_settings"])
    if candidate_id.startswith("fit-screen-"):
        d = config["model"]["deformation"]
        for key in ("initial_momenta", "initial_momenta_subjects"):
            d.pop(key, None)
        d["initial_control_points"] = os.path.relpath(root / search["controls"]["copy"], directory)
        d["initial_control_point_spacing"] = search["spacing"]
        config["optimization"]["max_iterations"] = 40
    validate_schema(config)


def measure_original_fit(root, manifest, candidate, run):
    from diffeoforge.result_report import collect_run_report

    verify_search(root, manifest)
    report = collect_run_report(run)
    outputs = {
        Path(r["path"]).name: run / "output" / r["path"]
        for r in report.inventory
        if "__Reconstruction__" in r["path"]
    }
    fits = {}
    for row in manifest["inputs"]["subjects"]:
        path = root / row["copy"]
        if sha256_file(path) != row["sha256"]:
            raise ValueError("Original target changed during fit measurement")
        matches = [
            p
            for name, p in outputs.items()
            if name.endswith("__subject_" + row["filename"] + ".vtk")
        ]
        if len(matches) != 1:
            raise ValueError("Original/reconstruction identity mismatch")
        fits[row["filename"]] = surface_fit(
            load_surface_mesh(path).geometry, load_surface_mesh(matches[0]).geometry
        )
    first_ids = {r["candidate_id"] for r in manifest["plan"]["stages"][0]["candidates"]}
    confirmation = candidate.candidate_id not in first_ids or (
        candidate.candidate_id in manifest["fit_search"]["confirmation_ids"]
    )
    return dict(
        fit_scope="full_targets" if confirmation else "screening",
        original_surface_fit=fits,
        subject_residual_p95={n: f["p95"] for n, f in fits.items()},
        surface_metric="area-stratified bidirectional point-to-triangle; 2048 samples/direction",
        surface_metric_limits="Sampled geometry, not anatomical correspondence or a pass threshold",
    )


def fit_key(candidate):
    fits = (candidate.metrics or {}).get("original_surface_fit", {})
    if not fits or candidate.metrics.get("invalid_face_count") != 0:
        return (float("inf"),) * 3
    return (
        max(f["p99"] / f["diagonal"] for f in fits.values()),
        max(f["p95"] / f["diagonal"] for f in fits.values()),
        sum(f["mean"] / f["diagonal"] for f in fits.values()) / len(fits),
    )


def search_plan(plan, spacing):
    values = plan.effective_values
    d, a, n = (
        values[k] for k in ("deformation_kernel_width", "attachment_kernel_width", "noise_std")
    )
    definitions = [
        ("Balanced motion", d, a, n),
        ("Broad motion", d * 2, a * 2, n),
        ("Local motion", d / 2, a, n),
        ("Detail and stronger fit", d, a / 2, n / 2),
    ]
    candidates = tuple(
        CalibrationCandidate(
            f"fit-screen-{i}",
            "Screen: " + label,
            tuple(
                sorted(
                    dict(
                        deformation_kernel_width=dw,
                        attachment_kernel_width=aw,
                        noise_std=nw,
                        initial_control_point_spacing=spacing,
                    ).items()
                )
            ),
            "Short scientific working-target fit; compare all originals before confirmation",
        )
        for i, (label, dw, aw, nw) in enumerate(definitions, 1)
    )
    first = replace(plan.stages[0], candidates=candidates, title="Bounded surface-fit search")
    revised = replace(
        plan, fingerprint="", stages=(first, *plan.stages[1:]), search_extension_lineage=()
    )
    payload = revised.provenance
    for key in ("fingerprint", "status", "pilot_subject_count"):
        payload.pop(key)
    return replace(revised, fingerprint=_canonical_hash(payload))


def create_search(source, minutes):
    from diffeoforge import reference_calibration_study as study

    if type(minutes) is not int or not 15 <= minutes <= 240:
        raise ValueError("Search time must be between 15 and 240 minutes")
    original = study.load_reference_calibration_study(source)
    if original.selected_candidate_ids or original.plan.qc_recalibration_source:
        raise ValueError(
            "Find fit starts at the first pilot stage; later stages retain their workflow"
        )
    manifest = study._verify_manifest(source)
    destination = source.parent / ("reference-fit-search-" + uuid4().hex[:12])
    config = copy.deepcopy(load_config(source / manifest["source_config"]["copy"]))
    cohort = manifest["inputs"]["full_cohort"]
    config["input"]["directory"] = cohort["directory"]
    config["input"]["template"] = cohort["template"]
    config["input"]["subject_pattern"] = cohort["subject_pattern"]
    template = load_surface_mesh(Path(cohort["template"]))
    _, spacing = control_grid(template.metadata.bounds)
    revised = search_plan(original.plan, spacing)
    config["project"]["parameter_provenance"]["recommendation"]["calibration_plan"] = (
        revised.provenance
    )
    launch_config = source.parent / (destination.name + ".yaml")
    study._write_yaml(launch_config, config, overwrite=False)
    return study.create_reference_calibration_study(
        launch_config,
        destination,
        pilot_max_iterations=40,
        plan_override=revised,
        fit_search=dict(
            minutes=minutes,
            confirmation_freeze_settings={
                key: config["optimization"][key]
                for key in ("freeze_template", "freeze_control_points")
            },
        ),
    )


def run_fit_search(runner, *, minutes=60, event_callback=None):
    from diffeoforge import reference_calibration_study as study

    preparation_started = time.monotonic()
    manifest = study._verify_manifest(runner.study_directory)
    snapshot = study.load_reference_calibration_study(runner.study_directory)
    if not manifest.get("fit_search"):
        snapshot = create_search(runner.study_directory, minutes)
        runner.study_directory = snapshot.study_directory
        manifest = study._verify_manifest(runner.study_directory)
    budget_root = Path(manifest["fit_search"]["budget_directory"])
    budget_file = budget_root / "fit-search-budget.json"
    budget = (
        study._read_json(budget_file, "fit search budget")
        if budget_file.exists()
        else {
            "spent_seconds": min(
                time.monotonic() - preparation_started, manifest["fit_search"]["minutes"] * 60
            ),
            "limit_seconds": manifest["fit_search"]["minutes"] * 60,
        }
    )
    remaining = budget["limit_seconds"] - budget["spent_seconds"]
    if (
        budget["limit_seconds"] != manifest["fit_search"]["minutes"] * 60
        or not np.isfinite(budget["spent_seconds"])
        or not 0 <= budget["spent_seconds"] <= budget["limit_seconds"]
    ):
        raise ValueError("Invalid persisted fit-search budget")
    if remaining <= 0:
        if not budget_file.exists():
            study._write_json(budget_file, budget, overwrite=False)
        raise ValueError("This search's time budget is exhausted. Review its saved results.")
    start = time.monotonic()
    lock = budget_root / "fit-search-active.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("This fit search is already running or requires crash recovery") from error
    timeout = threading.Timer(remaining, runner.request_cancel)
    timeout.daemon = True

    def emit(event):
        if event_callback:
            event_callback(event)

    try:
        # Reserve before execution. A crash cannot silently reset the budget.
        study._write_json(
            budget_file, dict(budget, spent_seconds=budget["limit_seconds"]), overwrite=True
        )
        timeout.start()
        emit(
            dict(
                event="fit_search_started",
                snapshot=snapshot,
                study_directory=str(snapshot.study_directory),
                minutes=manifest["fit_search"]["minutes"],
            )
        )
        if runner._cancel_requested:
            return snapshot
        snapshot = runner.run_current_stage(event_callback=emit)
        already = sum(c.candidate_id.startswith("continue-") for c in snapshot.candidates)
        for refinement in range(already, 2):
            if runner._cancel_requested or any(
                c.status != "completed" for c in snapshot.candidates
            ):
                return snapshot
            available = [
                c
                for c in snapshot.candidates
                if snapshot.visual_reviews.get(c.candidate_id) is not False
                and np.isfinite(fit_key(c)[0])
            ]
            current_manifest = study._verify_manifest(snapshot.study_directory)
            previous_id = current_manifest.get("adaptive_seed", {}).get("candidate_id")
            previous = next((c for c in available if c.candidate_id == previous_id), None)
            if previous is not None:
                before = previous.metrics["original_surface_fit"]
                available = [
                    c
                    for c in available
                    if all(
                        c.metrics["original_surface_fit"][name][key]
                        <= before[name][key] * (1 + 1e-9)
                        for name in before
                        for key in ("p95", "p99")
                    )
                ]
            if not available:
                return snapshot
            center = min(available, key=fit_key)
            # A confirmation already exists: reopening never queues another one.
            if any(
                c.metrics and c.metrics.get("fit_scope") == "full_targets"
                for c in snapshot.candidates
            ):
                return snapshot
            destination = study.next_reference_calibration_search_extension_destination(
                snapshot.study_directory
            )
            planned = next(
                c
                for c in snapshot.current_stage.candidates
                if c.candidate_id == center.candidate_id
            )
            values = {**snapshot.plan.effective_values, **planned.values}
            context = dict(
                candidate_id=center.candidate_id,
                iterations=80 if refinement == 0 else 200,
                values={
                    k: values[k]
                    for k in (
                        "attachment_kernel_width",
                        "deformation_kernel_width",
                        "initial_control_point_spacing",
                        "noise_std",
                    )
                },
            )
            limits = snapshot.search_extension_safety_limits or {
                k: (v / 8, v * 8) for k, v in context["values"].items()
            }
            if refinement == 0:
                context["finer_surface"] = True
                for key in ("attachment_kernel_width", "noise_std"):
                    context["values"][key] /= 2
            else:
                context["confirm_full_targets"] = True
            snapshot = study.create_reference_calibration_search_extension_study(
                snapshot.study_directory,
                destination,
                safety_limits=limits,
                continuation_context=context,
                confirm_full_targets=refinement == 1,
            )
            runner.study_directory = snapshot.study_directory
            emit(
                dict(
                    event="fit_search_extended",
                    snapshot=snapshot,
                    study_directory=str(snapshot.study_directory),
                    confirmation=refinement == 1,
                )
            )
            snapshot = runner.run_current_stage(event_callback=emit)
        return snapshot
    finally:
        timeout.cancel()
        used = min(remaining, time.monotonic() - start)
        try:
            study._write_json(
                budget_file,
                dict(budget, spent_seconds=budget["spent_seconds"] + used),
                overwrite=True,
            )
            emit(
                dict(
                    event="fit_search_stopped",
                    reason="time_budget" if used >= remaining else "review_required",
                    spent_seconds=budget["spent_seconds"] + used,
                    full_target_completed=any(
                        c.status == "completed"
                        and c.metrics
                        and c.metrics.get("fit_scope") == "full_targets"
                        for c in snapshot.candidates
                    ),
                )
            )
        finally:
            lock.rmdir()
