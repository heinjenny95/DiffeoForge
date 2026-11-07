"""Bounded original-source/time qualification of one unchanged ordinary field."""

import json
import time
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pilot_qualification import CRITERIA

VERSION = "ordinary-fixed-field-quality-v1"
COUNTS = (37, 73, 145, 289, 577)
TEMPORAL_TOLERANCE = 1e-4


def _surface(path):
    from diffeoforge.mesh_filter_worker import run_mesh_filter
    from diffeoforge.surface_io import load_surface_mesh

    mesh = load_surface_mesh(path).geometry
    v, f = np.asarray(mesh.vertices, float), np.asarray(mesh.triangles, int)
    nonpositive = np.count_nonzero(
        np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1) <= 0
    )
    return dict(
        intersecting_faces=len(run_mesh_filter("intersections", vertices=v, faces=f)["faces"]),
        nonpositive_faces=int(nonpositive),
        vertices=len(v),
        faces=len(f),
    )


def qualify(run, destination, *, cancelled=lambda: False, event_callback=None):
    """Evaluate saved coefficients only; never fit, smooth or replace native outputs."""
    from diffeoforge.mesh_filter_worker import mesh_filter_cancellation

    with mesh_filter_cancellation(cancelled):
        return _qualify(run, destination, cancelled=cancelled, event_callback=event_callback)


def _qualify(run, destination, *, cancelled, event_callback):
    from diffeoforge.reference_fixed_shooting import movement
    from diffeoforge.regional_evaluation import evaluate, field_inputs
    from diffeoforge.source_refinement import refine_evaluation
    from diffeoforge.surface_io import load_surface_mesh

    run, destination = Path(run), Path(destination)
    cache = {}
    data = field_inputs(run, cache)
    config = data.run_report.manifest["effective_config"]
    from diffeoforge.reference_ordinary_guard import validate

    validate(config, len(data.subject_labels))
    if not config["model"]["deformation"]["use_rk2"]:
        raise ValueError("This ordinary fixed-field qualification requires explicit RK2")
    actual_count = config["model"]["deformation"]["timepoints"]
    if not 2 <= actual_count <= COUNTS[-1]:
        raise ValueError("Optimizer time grid exceeds this bounded qualification contract")
    if cancelled():
        raise InterruptedError("Surface qualification cancelled; native fit retained")
    destination.mkdir()
    started = time.monotonic()
    source_row = next(r for r in data.run_report.manifest["inputs"] if r["role"] == "template")
    target_row = next(r for r in data.run_report.manifest["inputs"] if r["role"] == "subject")
    source = run / source_row["staged_path"]
    target = run / target_row["staged_path"]
    object_id, subject = config["model"]["object_id"], data.subject_labels[0]
    native_rows = [
        r
        for r in data.run_report.inventory
        if ("__Reconstruction__" + object_id + "__subject_") in r["path"]
        and r["path"].endswith("__subject_" + subject + ".vtk")
    ]
    if len(native_rows) != 1:
        raise ValueError("Ordinary native reconstruction is absent or ambiguous")
    native = run / "output" / native_rows[0]["path"]
    bindings = {
        source: source_row["geometry"]["sha256"],
        target: target_row["geometry"]["sha256"],
        native: native_rows[0]["sha256"],
    }

    def verify_bindings():
        if any(
            p.is_symlink() or not p.is_file() or sha256_file(p) != digest
            for p, digest in bindings.items()
        ):
            raise ValueError("Qualification input or native reconstruction changed")

    verify_bindings()
    original = load_surface_mesh(source).geometry
    target_geometry = load_surface_mesh(target).geometry
    diagonal = float(np.linalg.norm(np.ptp(original.vertices, axis=0)))
    target_diagonal = float(np.linalg.norm(np.ptp(target_geometry.vertices, axis=0)))
    if not min(diagonal, target_diagonal) > 0:
        raise ValueError("Fixed-field qualification requires nonempty source and target")
    policy = dict(
        version=VERSION,
        validation_timepoints=list(COUNTS),
        temporal_maximum_relative=TEMPORAL_TOLERANCE,
        optimizer_grid_criteria={
            k: CRITERIA["integration_" + k] for k in ("rms", "p95", "maximum")
        },
        native_export_criteria={k: CRITERIA["roundtrip_" + k] for k in ("rms", "maximum")},
        maximum_source_vertices=500_000,
        maximum_source_passes_per_grid=16,
        source_manifest_sha256=sha256_file(run / "manifest.json"),
        controls_sha256=sha256_file(data.control_points_path),
        momenta_sha256=sha256_file(data.momenta_path),
        geometry_bindings={str(p): digest for p, digest in bindings.items()},
        optimizer_updates=0,
        anatomical_approval=False,
    )
    (destination / "policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    before = _surface(source)
    if before["intersecting_faces"] or before["nonpositive_faces"]:
        raise ValueError("Original source geometry must be reviewed before this ordinary check")

    def sample(count, name, grid):
        verify_bindings()
        if cancelled():
            raise InterruptedError("Surface qualification cancelled; native fit retained")
        if event_callback:
            event_callback(
                dict(
                    event="qualification_phase",
                    message=(f"Checking the saved field on {count} time points; no new fitting."),
                )
            )
        result = evaluate(
            run,
            destination / name,
            count=count,
            _source=grid,
            cancelled=cancelled,
            event_callback=event_callback,
            _cache=cache,
        )
        result["whole_surface_sampling"] = True
        verify_bindings()
        return result

    actual = sample(actual_count, "original-optimizer-grid", source)
    reproduction = movement(native, Path(actual["endpoint"]["path"]), target_diagonal)
    verify_bindings()
    reproduction_passed = all(
        reproduction[k] <= policy["native_export_criteria"][k]
        for k in policy["native_export_criteria"]
    )
    if not reproduction_passed:
        (destination / "native-reproduction-failure.json").write_text(
            json.dumps(dict(policy=policy, observed=reproduction, optimizer_updates=0), indent=2)
            + "\n"
        )
        raise ValueError("Native export reproduction failed; saved native fit retained")
    coarse = actual if actual_count == COUNTS[0] else sample(COUNTS[0], "grid37", source)
    plan = dict(
        guidance=[],
        objects=[dict(id="focus", kernel_width=config["model"]["attachment"]["kernel_width"])],
        focus_regions=[],
    )
    checks = []
    fine = coarse
    for count in COUNTS[1:]:
        grid = Path(coarse["reference_source"]["path"])
        fine = sample(count, f"grid{count}", grid)
        fine = refine_evaluation(
            run,
            fine,
            destination / f"source-grid{count}",
            plan,
            cancelled=cancelled,
            event_callback=event_callback,
            cache=cache,
        )
        refined = Path(fine["reference_source"]["path"])
        if sha256_file(refined) != sha256_file(grid):
            coarse = sample(coarse["timepoints"], f"coarse-on-source{count}", refined)
        delta = movement(Path(coarse["endpoint"]["path"]), Path(fine["endpoint"]["path"]), diagonal)
        checks.append(dict(coarse=coarse["timepoints"], fine=count, **delta))
        (destination / "temporal-progress.json").write_text(json.dumps(checks, indent=2) + "\n")
        if delta["maximum"] <= TEMPORAL_TOLERANCE:
            break
        coarse = fine
    final_grid = Path(fine["reference_source"]["path"])
    actual_on_final = sample(actual_count, "optimizer-on-final-source", final_grid)
    accuracy = movement(
        Path(actual_on_final["endpoint"]["path"]), Path(fine["endpoint"]["path"]), diagonal
    )
    accuracy_passed = all(
        accuracy[k] <= policy["optimizer_grid_criteria"][k]
        for k in policy["optimizer_grid_criteria"]
    )
    surface = _surface(Path(fine["endpoint"]["path"]))
    refinement = fine.get("source_refinement") or {}
    spatial = not refinement.get("resource_limit", False)
    temporal = checks[-1]["maximum"] <= TEMPORAL_TOLERANCE
    passed = bool(
        reproduction_passed
        and accuracy_passed
        and spatial
        and temporal
        and not surface["intersecting_faces"]
        and not surface["nonpositive_faces"]
    )
    fine["starting_frame_qualification"] = dict(
        temporal_stable=temporal,
        temporal_checks=checks,
        optimizer_updates=0,
        purpose="Unchanged ordinary field on conforming original-source material points",
    )
    result = dict(
        version=VERSION,
        passed=passed,
        numerical_selection_suitable=passed,
        policy=policy,
        evaluation=fine,
        original_surface=before,
        final_surface=surface,
        native_export=dict(path=str(native), sha256=bindings[native]),
        native_export_reproduction=dict(passed=reproduction_passed, **reproduction),
        optimizer_grid_accuracy=dict(passed=accuracy_passed, **accuracy),
        temporal_grid_checks=checks,
        temporal_grid_stable=temporal,
        spatial_resolution_sufficient=spatial,
        whole_surface_sampling=True,
        source_surface_unchanged=True,
        optimizer_updates=0,
        anatomical_approval=False,
        qualification_wall_seconds=time.monotonic() - started,
    )
    field_inputs(run, cache)  # Recheck bound native/manifest/field identities at completion.
    verify_bindings()
    (destination / "quality.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def evaluate_and_measure(root, candidate, run, *, cancelled, event_callback):
    destination = (
        Path(root) / "ordinary-evaluations" / (candidate.candidate_id + "-" + uuid4().hex[:8])
    )
    destination.parent.mkdir(exist_ok=True)
    return qualify(run, destination, cancelled=cancelled, event_callback=event_callback)
