"""A source-bound, axis-separated density comparison of one reviewed joint fit.

The original study stays immutable. Three new joint fits share its learned
template, kernel, subjects, optimizer and initial deformation. The reference
keeps the learned control basis; finer nested bases add zero-momentum points.
"""

from __future__ import annotations

import copy
import math
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.config import load_config
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import CalibrationCandidate

VERSION = "nested-control-density-v1"
STAGE_ID = "timepoints"  # Retain the four-stage plan's stable on-disk identity.
FACTORS = (1.0, 0.8, 2.0 / 3.0)
DENSITIES = (1.0, 1.5, 2.0)


def source_fit(directory):
    """Resolve the currently chosen final-stage fit and its live approval."""
    from diffeoforge.reference_pilot_completion import _valid
    from diffeoforge.reference_stage_retention import _candidate

    snapshot = study.load_reference_calibration_study(directory)
    if len(snapshot.plan.stages) != 4 or study._read_json(
        snapshot.study_directory / study.STUDY_MANIFEST,
        "study",
    ).get("control_density"):
        raise ValueError("Choose the original reviewed joint pilot for a density comparison")
    stage = snapshot.plan.stages[-1]
    if snapshot.status == "completed":
        identifier = snapshot.selected_candidate_ids[stage.stage_id]
        candidate, _ = _candidate(snapshot.study_directory, stage.stage_id, identifier)
        # Completed-study reopening has verified the exact final anatomical decision.
        approved = True
    elif snapshot.current_stage and snapshot.current_stage.order == 4:
        candidates = [c for c in snapshot.candidates if snapshot.visual_reviews.get(c.candidate_id)]
        if len(candidates) != 1:
            raise ValueError("Finish choosing one reviewed saved fit before testing its density")
        candidate = candidates[0]
        approved = snapshot.visual_reviews.get(candidate.candidate_id) is True
    else:
        raise ValueError("Choose and approve the joint fit through Stage 3 first")
    context = replace(snapshot, current_stage=stage, candidates=(candidate,))
    if not approved or not _valid(candidate, context):
        raise ValueError("A complete, valid, currently approved joint fit is required")
    return context, candidate


def _regular_grid(points, spacing):
    """The native 3-D bounding-box lattice; existing learned points are retained."""
    lower, upper = np.min(points, axis=0), np.max(points, axis=0)
    axes = []
    for lo, hi in zip(lower, upper, strict=True):
        offset = 0.5 * (hi - lo - spacing * math.floor((hi - lo) / spacing))
        axes.append(np.arange(lo + offset, hi + 1e-10, spacing))
    return np.column_stack([a.ravel() for a in np.meshgrid(*axes)])


def _augment(existing, grid, spacing, target_count=None):
    # Avoid almost coincident basis points. Original coordinates and order are
    # untouched; each new lattice is already internally spaced by `spacing`.
    retained, nearest = [], []
    for start in range(0, len(grid), 128):
        block = grid[start : start + 128]
        distance2 = np.sum((block[:, None, :] - existing[None, :, :]) ** 2, axis=2)
        minimum = np.min(distance2, axis=1)
        valid = minimum >= (0.25 * spacing) ** 2
        retained.append(block[valid])
        nearest.append(minimum[valid])
    added = np.concatenate(retained, axis=0)
    if not len(added):
        raise ValueError("The proposed finer grid adds no distinct control points")
    if target_count is not None:
        count = target_count - len(existing)
        if count <= 0 or count > len(added):
            raise ValueError("The finer lattice cannot supply the declared density")
        # Deterministic farthest-first coverage selects a bounded number of
        # lattice points, keeping the existing basis and all earlier additions.
        minimum = np.concatenate(nearest)
        chosen = []
        for _ in range(count):
            index = int(np.argmax(minimum))
            chosen.append(index)
            minimum = np.minimum(minimum, np.sum((added - added[index]) ** 2, axis=1))
            minimum[chosen] = -1
        added = added[chosen]
    return np.concatenate((existing, added), axis=0)


def default_directory(source):
    root = Path(source).resolve()
    return root.parent / (root.name + "-control-density-01")


def prepare(source, destination=None):
    """Prepare/reopen a separate comparison, never launching a scientific process."""
    from diffeoforge.mesh import read_vtk_points
    from diffeoforge.reference_adaptive_calibration import bind_learned_seed
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.reference_pca_deformations import _write_momenta
    from diffeoforge.reference_sequential_fit import _fingerprint

    original, candidate = source_fit(source)
    root = Path(destination or default_directory(source)).resolve()
    if root == original.study_directory or original.study_directory in root.parents:
        raise ValueError("Density comparison must be a separate sibling study")
    if root.exists():
        snapshot = study.load_reference_calibration_study(root)
        # Reopening already verified this exact manifest and lineage. Avoid
        # repeating the source's full-cohort handoff verification in one action.
        record = study._read_json(root / study.STUDY_MANIFEST, "study").get("control_density", {})
        if Path(record.get("source_directory", "")).resolve() != original.study_directory:
            raise ValueError("Existing density study belongs to another pilot")
        return snapshot
    root.mkdir(parents=True)
    # Failed preparation remains diagnosable; never remove a partially written
    # scientific directory or silently replace it on retry.
    parent = study._verify_manifest(original.study_directory)
    config = copy.deepcopy(load_config(candidate.config_path))
    seed = bind_learned_seed(original, candidate.candidate_id, root / "source")
    template = root / "source" / seed["files"]["template"]["copy"]
    template_copy = root / "inputs" / "template" / template.name
    study._copy_bound(template, template_copy, sha256_file(template))
    template = template_copy
    controls = root / "source" / seed["files"]["control_points"]["copy"]
    momenta = root / "source" / seed["files"]["momenta"]["copy"]
    base = np.loadtxt(controls, ndmin=2)
    weights = read_deformetrica_momenta(momenta, allow_singleton=True)
    if base.shape[1:] != (3,) or weights.shape != (len(seed["subject_labels"]), len(base), 3):
        raise ValueError("Saved common control basis and ordered momenta differ")
    if not np.isfinite(base).all() or not np.isfinite(weights).all():
        raise ValueError("Saved common basis must be finite")
    vertices = np.asarray(read_vtk_points(template))
    spacing = float(config["model"]["deformation"]["initial_control_point_spacing"])
    definitions, grids = [], []
    for index, factor in enumerate(FACTORS, 1):
        values = (
            base.copy()
            if index == 1
            else _augment(
                grids[-1],
                _regular_grid(vertices, spacing * factor),
                spacing * factor,
                math.ceil(len(base) * DENSITIES[index - 1]),
            )
        )
        grids.append(values)
        identifier = f"density-{index:02d}"
        folder = root / "density-inputs" / identifier
        folder.mkdir(parents=True)
        cp, mp = folder / "control-points.txt", folder / "momenta.txt"
        np.savetxt(cp, values, fmt="%.17g")
        initial = np.zeros((len(weights), len(values), 3))
        initial[:, : len(base)] = weights
        _write_momenta(mp, initial)
        definitions.append(
            dict(
                candidate_id=identifier,
                factor=factor,
                count=len(values),
                spacing=spacing * factor,
                controls=dict(copy=study._relative_path(root, cp), sha256=sha256_file(cp)),
                momenta=dict(copy=study._relative_path(root, mp), sha256=sha256_file(mp)),
            )
        )
    stage = replace(
        original.plan.stages[-1],
        stage_id=STAGE_ID,
        title="Control-point density at selected settings",
        candidates=tuple(
            CalibrationCandidate(
                d["candidate_id"],
                ("Matched reference" if i == 0 else f"Denser grid {i}") + f" — {d['count']} points",
                (
                    ("initial_control_point_spacing", d["spacing"]),
                    ("timepoints", float(config["model"]["deformation"]["timepoints"])),
                ),
                "Same learned starting deformation and all other settings; "
                "only the common basis grows.",
            )
            for i, d in enumerate(definitions)
        ),
        locked_from_previous_stages=(
            "attachment_kernel_width",
            "deformation_kernel_width",
            "noise_std",
        ),
        decision_rule="Compare matched-reference and finer-basis fits. "
        "No automatic density optimum.",
        evidence_required=(
            "all-subject surface fit",
            "endpoint changes on common geometry",
            "optimizer stop",
            "fresh all-subject anatomical QC",
            "fixed-state integration",
        ),
    )
    plan = _fingerprint(
        replace(
            original.plan,
            stages=(*original.plan.stages[:3], stage),
            template_filename=template.name,
            template_sha256=sha256_file(template),
            search_extension_lineage=(),
            qc_recalibration_source=(),
        )
    )
    # Bind original full-resolution pilot targets, not a new A–E screening queue.
    inputs = copy.deepcopy(parent["inputs"])
    inputs["template"] = dict(
        copy=study._relative_path(root, template), sha256=sha256_file(template)
    )
    for row in inputs["subjects"]:
        study._copy_bound(original.study_directory / row["copy"], root / row["copy"], row["sha256"])
    source_copy = root / "source" / "atlas.yaml"
    study._write_yaml(source_copy, config, overwrite=False)
    record = dict(
        version=VERSION,
        source_directory=str(original.study_directory),
        source_manifest_sha256=sha256_file(original.study_directory / study.STUDY_MANIFEST),
        source_stage=original.current_stage.stage_id,
        source_candidate=candidate.candidate_id,
        source_binding=study._candidate_review_binding(candidate),
        original_control_count=len(base),
        subject_labels=seed["subject_labels"],
        template=inputs["template"],
        base_controls=dict(copy=study._relative_path(root, controls), sha256=sha256_file(controls)),
        base_momenta=dict(copy=study._relative_path(root, momenta), sha256=sha256_file(momenta)),
        variants=definitions,
        initialization="Original common coordinates/momenta preserved; extra momenta start at zero",
        comparison="Matched continuation reference plus two nested finer common bases",
        limitation="A finite density comparison is sensitivity evidence, "
        "not a universal optimum or anatomical approval",
    )
    manifest = dict(
        study_version=study.STUDY_VERSION,
        study_id=f"reference-density-{uuid4().hex[:12]}",
        plan_fingerprint=plan.fingerprint,
        plan=plan.provenance,
        pilot_max_iterations=int(config["optimization"]["max_iterations"]),
        template_diagonal=parent["template_diagonal"],
        launcher=parent["launcher"],
        source_config=dict(
            copy=study._relative_path(root, source_copy), sha256=sha256_file(source_copy)
        ),
        inputs=inputs,
        control_density=record,
        scientific_boundary="Only control density varies; "
        "prior approvals remain in the immutable source study",
    )
    study._write_json(root / study.STUDY_MANIFEST, manifest, overwrite=False)
    write_text_safely(
        root / study.STUDY_DIGEST, sha256_file(root / study.STUDY_MANIFEST) + "\n", overwrite=False
    )
    study._append_event(
        root,
        "study_created",
        dict(
            study_id=manifest["study_id"],
            plan_fingerprint=plan.fingerprint,
            manifest_sha256=sha256_file(root / study.STUDY_MANIFEST),
        ),
    )
    keys = {"event_version", "sequence", "previous_hash", "event", "event_hash"}
    for event in study._load_events(original.study_directory):
        if event["event"] == "stage_selected" and event["stage_id"] in {
            s.stage_id for s in plan.stages[:3]
        }:
            study._append_event(
                root, "stage_selected", {k: v for k, v in event.items() if k not in keys}
            )
    values, _ = study._selected_state(study._load_events(root))
    study._prepare_stage(root, manifest, plan, stage, values)
    return study.load_reference_calibration_study(root)


def configure_trial(config, root, manifest, candidate_id):
    record = manifest["control_density"]
    if len(record["variants"]) != 3 or [v["candidate_id"] for v in record["variants"]] != [
        "density-01",
        "density-02",
        "density-03",
    ]:
        raise ValueError(
            "Density comparison must contain the matched reference and two finer grids"
        )
    variant = next(d for d in record["variants"] if d["candidate_id"] == candidate_id)
    directory = root / "stages" / f"04-{STAGE_ID}" / candidate_id
    deformation = config["model"]["deformation"]
    for key, field in (("initial_control_points", "controls"), ("initial_momenta", "momenta")):
        deformation[key] = os.path.relpath(root / variant[field]["copy"], directory).replace(
            "\\", "/"
        )
    deformation["initial_momenta_subjects"] = list(record["subject_labels"])


def verify_source(root, manifest):
    """Fail closed on source withdrawal, settings drift, changed grids or weights."""
    from diffeoforge.reference_pca import read_deformetrica_momenta

    record = manifest["control_density"]
    source = Path(record["source_directory"]).resolve()
    if source == root or record["version"] != VERSION:
        raise ValueError("Invalid density-study lineage")
    if sha256_file(source / study.STUDY_MANIFEST) != record["source_manifest_sha256"]:
        raise ValueError("Density source manifest changed")
    parent, candidate = source_fit(source)
    if (
        parent.current_stage.stage_id != record["source_stage"]
        or candidate.candidate_id != record["source_candidate"]
        or study._candidate_review_binding(candidate) != record["source_binding"]
    ):
        raise ValueError("Density source choice or approved output changed")
    expected = load_config(root / manifest["source_config"]["copy"])
    if expected != load_config(candidate.config_path):
        raise ValueError("Density source scientific settings changed")
    parent_manifest = study._read_json(source / study.STUDY_MANIFEST, "study")
    if manifest["inputs"]["subjects"] != parent_manifest["inputs"]["subjects"]:
        raise ValueError("Density comparison cohort changed")
    for item in [
        record["template"],
        record["base_controls"],
        record["base_momenta"],
        *(d[k] for d in record["variants"] for k in ("controls", "momenta")),
    ]:
        if sha256_file(study._safe_study_path(root, item["copy"])) != item["sha256"]:
            raise ValueError("Density comparison initialization changed")
    base = np.loadtxt(root / record["base_controls"]["copy"], ndmin=2)
    weights = read_deformetrica_momenta(root / record["base_momenta"]["copy"], allow_singleton=True)
    previous = base
    if len(record["variants"]) != 3:
        raise ValueError("Density comparison must have three variants")
    for index, variant in enumerate(record["variants"]):
        cp = np.loadtxt(root / variant["controls"]["copy"], ndmin=2)
        mp = read_deformetrica_momenta(root / variant["momenta"]["copy"], allow_singleton=True)
        if (
            variant["factor"] != FACTORS[index]
            or variant["candidate_id"] != f"density-{index + 1:02d}"
            or variant["spacing"]
            != expected["model"]["deformation"]["initial_control_point_spacing"] * FACTORS[index]
            or (index and len(cp) <= len(previous))
            or cp.shape != (variant["count"], 3)
            or len(cp) != math.ceil(len(base) * DENSITIES[index])
            or not np.isfinite(cp).all()
            or not np.isfinite(mp).all()
            or not np.array_equal(cp[: len(previous)], previous)
            or mp.shape != (len(weights), len(cp), 3)
            or not np.array_equal(mp[:, : len(base)], weights)
            or np.any(mp[:, len(base) :])
        ):
            raise ValueError("Density common-basis initialization differs")
        previous = cp
        path = root / "stages" / f"04-{STAGE_ID}" / variant["candidate_id"] / "atlas.yaml"
        if path.exists():
            value = load_config(path)
            a, b = copy.deepcopy(value["model"]), copy.deepcopy(expected["model"])
            for model in (a, b):
                for key in (
                    "initial_control_points",
                    "initial_momenta",
                    "initial_momenta_subjects",
                    "initial_control_point_spacing",
                ):
                    model["deformation"].pop(key, None)
            if (
                a != b
                or value["runtime"] != expected["runtime"]
                or value["optimization"] != expected["optimization"]
                or value["model"]["deformation"]["initial_control_point_spacing"]
                != variant["spacing"]
                or value["model"]["deformation"]["initial_momenta_subjects"]
                != record["subject_labels"]
            ):
                raise ValueError("Only control density may change in this comparison")
            for field, key in (
                ("initial_control_points", "controls"),
                ("initial_momenta", "momenta"),
            ):
                if (path.parent / value["model"]["deformation"][field]).resolve() != (
                    root / variant[key]["copy"]
                ).resolve():
                    raise ValueError("Density input file binding changed")


def run_next(runner, *, event_callback=None):
    snapshot = study.load_reference_calibration_study(runner.study_directory)
    manifest = study._verify_manifest(snapshot.study_directory)
    if "control_density" not in manifest or snapshot.status == "completed":
        raise ValueError("Open an unfinished density comparison")
    unreviewed = [
        c
        for c in snapshot.candidates
        if c.status == "completed" and c.candidate_id not in snapshot.visual_reviews
    ]
    if unreviewed:
        raise ValueError("Review the completed density fit before running the next one")
    pending = next((c for c in snapshot.candidates if c.status != "completed"), None)
    if pending is None:
        return snapshot
    result = runner.run_current_stage(
        candidate_ids={pending.candidate_id}, event_callback=event_callback
    )
    # Pause after every density variant, not only after the whole queue.
    if result.status != "awaiting_review":
        study._append_event(
            snapshot.study_directory, "stage_awaiting_review", dict(stage_id=STAGE_ID)
        )
    return study.load_reference_calibration_study(snapshot.study_directory)


def validate_dispatch(snapshot, candidate_ids):
    """Even a direct runner call cannot batch, skip or approve density variants."""
    if candidate_ids is None or len(candidate_ids) != 1:
        raise ValueError("Density comparisons run one explicitly chosen next fit at a time")
    if any(
        c.status == "completed" and c.candidate_id not in snapshot.visual_reviews
        for c in snapshot.candidates
    ):
        raise ValueError("Review the completed density fit before running the next one")
    pending = next((c for c in snapshot.candidates if c.status != "completed"), None)
    if pending is None or candidate_ids != {pending.candidate_id}:
        raise ValueError("Density comparisons cannot skip the matched reference or next grid")


def measure_fit(root, manifest, candidate, run):
    from diffeoforge.reference_fit_search import surface_fit
    from diffeoforge.reference_holdout_study import _trained_model_artifacts
    from diffeoforge.reference_pilot_completion import legacy, movement
    from diffeoforge.reference_stage_retention import _candidate
    from diffeoforge.surface_io import load_surface_mesh

    _, reconstructions = legacy._reconstructions(run)
    fits = {}
    for row in manifest["inputs"]["subjects"]:
        fits[row["filename"]] = surface_fit(
            load_surface_mesh(root / row["copy"]).geometry,
            load_surface_mesh(reconstructions[row["filename"]]).geometry,
        )
    _, _, controls, *_ = _trained_model_artifacts(run)
    count = len(np.loadtxt(controls, ndmin=2))
    record = manifest["control_density"]
    expected = next(
        v["count"] for v in record["variants"] if v["candidate_id"] == candidate.candidate_id
    )
    if count != expected:
        raise ValueError("Native density fit used a different control-point count")
    _, saved = source_fit(record["source_directory"])
    references = {"saved_fit": study.calibration_candidate_run_directory(saved)}
    events = study._load_events(root)
    if candidate.candidate_id != "density-01" and any(
        e["event"] == "candidate_completed" and e.get("candidate_id") == "density-01"
        for e in events
    ):
        reference, _ = _candidate(root, STAGE_ID, "density-01")
        references["matched_reference"] = study.calibration_candidate_run_directory(reference)
    changes = {}
    for label, reference_run in references.items():
        _, prior = legacy._reconstructions(reference_run)
        changes[label] = {
            name: movement(prior[name], path, fits[name]["diagonal"])
            for name, path in reconstructions.items()
        }
    return dict(
        fit_scope="full_targets",
        original_surface_fit=fits,
        subject_residual_p95={name: fit["p95"] for name, fit in fits.items()},
        surface_metric="area-stratified bidirectional point-to-triangle; 2048 samples/direction",
        control_point_count=count,
        density_endpoint_changes=changes,
    )


def rows(snapshot):
    """Lightweight comparison from recorded, bound metrics; no geometry processing."""
    manifest = study._read_json(snapshot.study_directory / study.STUDY_MANIFEST, "study")
    record = manifest.get("control_density")
    if not record:
        return []
    from diffeoforge.reference_stage_retention import _candidate

    baseline, _ = _candidate(
        Path(record["source_directory"]),
        record["source_stage"],
        record["source_candidate"],
    )
    candidates = snapshot.candidates or tuple(
        _candidate(snapshot.study_directory, STAGE_ID, d["candidate_id"])[0]
        for d in record["variants"]
    )
    reviews = snapshot.visual_reviews
    if snapshot.status == "completed":
        reviews = study._load_candidate_reviews(
            study._load_events(snapshot.study_directory)
            + study._read_review_journal(snapshot.study_directory),
            STAGE_ID,
            candidates,
        )
    result = [("Original approved fit", record["original_control_count"], baseline.metrics, True)]
    result.extend(
        (
            c.label,
            (c.metrics or {}).get("control_point_count", d["count"]),
            c.metrics,
            reviews.get(c.candidate_id),
        )
        for c, d in zip(candidates, record["variants"], strict=True)
    )
    output = []
    for label, count, metrics, approved in result:
        fits = (metrics or {}).get("original_surface_fit", {})
        changes = (metrics or {}).get("density_endpoint_changes", {}).get("matched_reference", {})
        output.append(
            dict(
                label=label,
                count=count,
                approved=approved,
                worst_p95=max((f["p95"] / f["diagonal"] for f in fits.values()), default=None),
                mean_p95=float(np.mean([f["p95"] / f["diagonal"] for f in fits.values()]))
                if fits
                else None,
                endpoint_p95=max((v["p95"] for v in changes.values()), default=None),
                converged=(metrics or {}).get("converged"),
                runtime=(metrics or {}).get("runtime_seconds"),
            )
        )
    return output


def verify_decision(snapshot):
    if (
        len(snapshot.candidates) != 3
        or any(c.status != "completed" for c in snapshot.candidates)
        or any(c.candidate_id not in snapshot.visual_reviews for c in snapshot.candidates)
    ):
        raise ValueError(
            "Complete and review the matched reference and both denser fits before finishing"
        )


def report(root):
    """Report during atomic finalization, without reopening a half-finished ledger."""
    from diffeoforge.reference_calibration import reference_calibration_plan_from_provenance
    from diffeoforge.reference_stage_retention import _candidate

    manifest = study._read_json(root / study.STUDY_MANIFEST, "study")
    candidates = tuple(
        _candidate(root, STAGE_ID, d["candidate_id"])[0]
        for d in manifest["control_density"]["variants"]
    )
    snapshot = study.ReferenceCalibrationStudySnapshot(
        root,
        manifest["study_id"],
        reference_calibration_plan_from_provenance(manifest["plan"]),
        "awaiting_review",
        None,
        candidates,
        {},
        {},
        0,
        None,
        None,
        None,
        visual_reviews=study._load_candidate_reviews(
            study._load_events(root) + study._read_review_journal(root),
            STAGE_ID,
            candidates,
        ),
    )
    return dict(manifest["control_density"], comparisons=rows(snapshot))


def report_html(value):
    import html

    body = ""
    for row in value["comparisons"]:
        distance = "—" if row["worst_p95"] is None else f"{row['worst_p95'] * 100:.5g}%"
        change = "—" if row["endpoint_p95"] is None else f"{row['endpoint_p95'] * 100:.5g}%"
        review = (
            "Approved"
            if row["approved"] is True
            else "Rejected"
            if row["approved"] is False
            else "Not reviewed"
        )
        body += (
            f"<tr><td>{html.escape(row['label'])}</td><td>{row['count']}</td>"
            f"<td>{distance}</td><td>{change}</td><td>{review}</td></tr>"
        )
    return (
        "<h2>Control-point density of the chosen fit</h2><p>Only the common basis changed. "
        "Kernel widths, noise, time resolution, target geometry "
        "and optimizer settings stayed fixed. "
        "Existing controls/momenta were retained; extra momenta started at zero. "
        "Each new fit required its own review. "
        "The original pilot and approvals remain unchanged.</p>"
        "<table><tr><th>Fit</th><th>Points</th><th>Worst specimen p95 / size</th>"
        "<th>Endpoint p95 change / size vs matched reference</th><th>Review</th></tr>"
        + body
        + "</table><p>Sampled geometry and sensitivity, not a universal optimal count.</p>"
    )
