"""Prospective, bounded final qualification, independent of anatomy decisions.

Legacy refit comparisons remain historical evidence. This protocol appends one
warm, tighter-tolerance checkpoint, then shoots that same state on nested grids.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config, validate_schema
from diffeoforge.mesh import read_vtk_points, sha256_file
from diffeoforge.reference_adaptive_calibration import apply_seed, bind_learned_seed
from diffeoforge.reference_calibration import CalibrationCandidate, CalibrationCandidateAssessment
from diffeoforge.reference_fixed_shooting import movement, shoot

VERSION = "independent-pilot-qualification-v1"
CRITERIA = dict(
    optimizer_geometry_rms=0.005,
    optimizer_objective_relative=0.01,
    optimizer_velocity_relative=0.01,
    integration_rms=0.005,
    integration_p95=0.01,
    integration_maximum=0.02,
    roundtrip_rms=1e-5,
    roundtrip_maximum=1e-4,
)


def declarations(events):
    return tuple(e for e in events if e["event"] == "pilot_qualification_declared")


def overlay_plan(plan, events):
    changed = False
    for e in declarations(events):
        row = e["candidate"]
        if e.get("version") != VERSION or e["stage_id"] != plan.stages[-1].stage_id:
            raise ValueError("Unknown pilot qualification declaration")
        stage = plan.stages[-1]
        if stage.order != 4 or row["candidate_id"] in {c.candidate_id for c in stage.candidates}:
            raise ValueError("Invalid pilot qualification identity")
        candidate = CalibrationCandidate(
            row["candidate_id"],
            row["label"],
            tuple(sorted(row["parameter_values"].items())),
            row["rationale"],
        )
        plan = replace(
            plan,
            stages=(*plan.stages[:-1], replace(stage, candidates=(*stage.candidates, candidate))),
        )
        changed = True
    if changed:
        payload = plan.provenance
        for key in ("fingerprint", "status", "pilot_subject_count"):
            payload.pop(key)
        plan = replace(plan, fingerprint=study._canonical_hash(payload))
    return plan


def _configuration(root, source, folder, seed, iterations, tolerance, count=None):
    config = copy.deepcopy(load_config(source.config_path))
    config["input"]["directory"] = str(
        (source.config_path.parent / config["input"]["directory"]).resolve()
    )
    apply_seed(config, root=root, candidate_directory=folder, seed=seed, initialization="warm")
    config["optimization"]["max_iterations"] = iterations
    config["optimization"]["convergence_tolerance"] = tolerance
    if count is not None:
        config["model"]["deformation"]["timepoints"] = count
    validate_schema(config)
    return config


def verify_declaration(root, event, events):
    """Verify sources and prospective criteria before considering any outcome."""
    earlier = tuple(e for e in events if e["sequence"] < event["sequence"])
    source = event["source"]
    completed = next(
        (
            e
            for e in reversed(earlier)
            if e["event"] == "candidate_completed"
            and e.get("candidate_id") == source["candidate_id"]
            and e.get("stage_id") == event["stage_id"]
        ),
        None,
    )
    if completed is None or completed["event_hash"] != source["completed_event_hash"]:
        raise ValueError("Qualification source completion changed")
    prepared = study._prepared_candidates(root, earlier, event["stage_id"])[source["candidate_id"]]
    state = study.CalibrationStudyCandidateState(
        source["candidate_id"],
        "Source",
        "completed",
        study._safe_study_path(root, prepared["config"]),
        study._safe_study_path(root, completed["run_directory"]),
        completed["metrics"],
        None,
        1,
    )
    if study._candidate_review_binding(state) != source["binding"]:
        raise ValueError("Qualification source identity changed")
    if event["criteria"] != CRITERIA or event["version"] != VERSION:
        raise ValueError("Qualification criteria differ from the declared protocol")
    seed = event["continuation_seed"]
    if (
        seed["candidate_id"] != source["candidate_id"]
        or seed["source_manifest_sha256"] != source["binding"]["run_manifest_sha256"]
    ):
        raise ValueError("Qualification initialization differs from source")
    for bound in seed["files"].values():
        path = study._safe_study_path(root, bound["copy"])
        if sha256_file(path) != bound["sha256"]:
            raise ValueError("Qualification initial field changed")
    config_path = study._safe_study_path(root, event["config"])
    expected = _configuration(
        root,
        state,
        config_path.parent,
        seed,
        event["iterations"],
        event["convergence_tolerance"],
        event.get("refinement_timepoints"),
    )
    refinement = event.get("refinement_timepoints")
    if (
        refinement is not None
        and refinement != 2 * int(seed["model"]["deformation"]["timepoints"]) - 1
    ):
        raise ValueError("Finer-model declaration changed its nested grid")
    if event["candidate"]["parameter_values"] != {
        "timepoints": float(expected["model"]["deformation"]["timepoints"])
    }:
        raise ValueError("Qualification candidate differs from its temporal grid")
    if load_config(config_path) != expected or sha256_file(config_path) != event["config_sha256"]:
        raise ValueError("Qualification configuration changed")
    return state


def prepare(snapshot, *, candidate_id=None, iterations=100, finer_model=False):
    if snapshot.current_stage is None or snapshot.current_stage.order != 4:
        raise ValueError("Final qualification belongs to Stage 4")
    if any(c.status == "orphaned" for c in snapshot.candidates):
        raise ValueError("Wait for the current fit to finish")
    if type(iterations) is not int or not 1 <= iterations <= 20_000:
        raise ValueError("Qualification iteration budget must be 1–20000")
    if not any(c.metrics for c in snapshot.candidates):
        from diffeoforge.reference_stage_retention import register_previous_fit

        snapshot = register_previous_fit(snapshot, for_qualification=True)
    eligible = [
        c
        for c in snapshot.candidates
        if c.metrics
        and c.metrics.get("invalid_face_count") == 0
        and c.metrics.get("fit_scope") not in {"screening", "working_targets"}
        and c.metrics.get("subject_reconstruction_count") == snapshot.plan.pilot_subject_count
        and snapshot.visual_reviews.get(c.candidate_id) is not False
    ]
    if candidate_id:
        eligible = [c for c in eligible if c.candidate_id == candidate_id]
    if not eligible:
        raise ValueError("Choose a complete, valid joint fit that you have not rejected")
    # Prefer explicit approval; otherwise the finest completed state, with fresh
    # checkpoint QC mandatory. This is an initialization rule, not a winner.
    definitions = {c.candidate_id: c for c in snapshot.current_stage.candidates}
    source = max(
        eligible,
        key=lambda c: (
            snapshot.visual_reviews.get(c.candidate_id) is True,
            definitions[c.candidate_id].values.get(
                "timepoints", snapshot.selected_values.get("timepoints", 10)
            ),
        ),
    )
    root = snapshot.study_directory
    folder = root / "qualification" / uuid4().hex
    seed = bind_learned_seed(snapshot, source.candidate_id, folder)
    for bound in seed["files"].values():
        bound["copy"] = study._relative_path(root, folder / bound["copy"])
    tolerance = min(float(seed["optimization"]["convergence_tolerance"]), 1e-6)
    count = 2 * int(seed["model"]["deformation"]["timepoints"]) - 1 if finer_model else None
    config = _configuration(root, source, folder, seed, iterations, tolerance, count)
    path = folder / "atlas.yaml"
    study._write_yaml(path, config, overwrite=False)
    values = {"timepoints": float(config["model"]["deformation"]["timepoints"])}
    candidate = CalibrationCandidate(
        "qualification-" + folder.name,
        "Finer model — review and qualify" if finer_model else "Saved model — numerical check",
        tuple(values.items()),
        "One tighter optimizer check, then fixed-state nested-grid Shooting; fresh QC required.",
    )
    completed = next(
        e
        for e in reversed(study._load_events(root))
        if e["event"] == "candidate_completed"
        and e.get("candidate_id") == source.candidate_id
        and e.get("stage_id") == snapshot.current_stage.stage_id
    )
    event = dict(
        version=VERSION,
        stage_id=snapshot.current_stage.stage_id,
        candidate=candidate.as_manifest(),
        config=study._relative_path(root, path),
        config_sha256=sha256_file(path),
        continuation_seed=seed,
        criteria=dict(CRITERIA),
        iterations=iterations,
        convergence_tolerance=tolerance,
        refinement_timepoints=count,
        source=dict(
            candidate_id=source.candidate_id,
            completed_event_hash=completed["event_hash"],
            binding=study._candidate_review_binding(source),
        ),
    )
    study._append_event(root, "pilot_qualification_declared", event)
    return study.load_reference_calibration_study(root), candidate.candidate_id


def _reconstructions(run):
    from diffeoforge.reference_calibration_metrics import (
        _inventory_vtk,
        _subject_from_reconstruction_name,
    )
    from diffeoforge.reference_pca import load_reference_momenta

    inputs = load_reference_momenta(run)
    rows = _inventory_vtk(inputs.run_report, "__Reconstruction__")
    values = {_subject_from_reconstruction_name(Path(name).name): path for name, path in rows}
    if set(values) != set(inputs.subject_labels):
        raise ValueError("Qualification requires every ordered subject reconstruction")
    return inputs, values


def optimizer_check(source_run, checkpoint_run, scales, template_scale):
    """Local state movement, independent from temporal discretization error."""
    from diffeoforge.reference_holdout_study import _trained_model_artifacts

    before, a = _reconstructions(source_run)
    after, b = _reconstructions(checkpoint_run)
    if before.subject_labels != after.subject_labels or set(scales) != set(a):
        raise ValueError("Optimizer check cohort/order differs")
    ta, *_ = _trained_model_artifacts(source_run)
    tb, *_ = _trained_model_artifacts(checkpoint_run)
    vertices = np.asarray(read_vtk_points(ta))
    probes = np.concatenate(
        (
            before.control_points,
            vertices[np.linspace(0, len(vertices) - 1, min(256, len(vertices)), dtype=int)],
        )
    )
    width = float(
        before.run_report.manifest["effective_config"]["model"]["deformation"]["kernel_width"]
    )
    other = after.run_report.manifest["effective_config"]["model"]["deformation"]["kernel_width"]
    if width != other:
        raise ValueError("Optimizer check changed its deformation ruler")

    def velocity(inputs):
        kernel = np.exp(
            -np.sum((probes[:, None] - inputs.control_points[None]) ** 2, axis=2) / width**2
        )
        return np.einsum("ij,sjk->sik", kernel, inputs.momenta)

    va, vb = velocity(before), velocity(after)
    numerator = np.sqrt(np.mean((va - vb) ** 2, axis=(1, 2)))
    denominator = np.maximum(np.sqrt(np.mean(va**2, axis=(1, 2))), template_scale * 1e-12)
    return dict(
        template=movement(ta, tb, template_scale),
        subjects={name: movement(a[name], b[name], scales[name]) for name in a},
        velocity_relative={
            name: float(numerator[i] / denominator[i])
            for i, name in enumerate(before.subject_labels)
        },
        probe_count=len(probes),
        probe_rule="source controls and up to 256 uniformly indexed source template vertices",
    )


def failed_gates(
    optimizer, integration, roundtrip, *, converged, objective_relative, valid_geometry=True
):
    failures = []
    values = [
        objective_relative,
        *optimizer["velocity_relative"].values(),
        *optimizer["template"].values(),
    ]
    for rows in (optimizer["subjects"], roundtrip, *integration.values()):
        values.extend(v for row in rows.values() for v in row.values())
    if any(isinstance(v, bool) or not np.isfinite(v) or v < 0 for v in values):
        raise ValueError("Qualification measurements must be finite and nonnegative")
    if not valid_geometry:
        failures.append(
            "Checkpoint geometry or cohort is invalid: inspect the saved result; it cannot qualify"
        )
    if not converged:
        failures.append(
            "Optimizer check reached its cap: continue the saved checkpoint. "
            "Its anatomy remains available for review"
        )
    if objective_relative > CRITERIA["optimizer_objective_relative"]:
        failures.append(
            "Objective still changes: continue the saved checkpoint before qualifying it"
        )
    if (
        max([optimizer["template"]["rms"], *(r["rms"] for r in optimizer["subjects"].values())])
        > CRITERIA["optimizer_geometry_rms"]
    ):
        failures.append(
            "Learned geometry still moves under tighter optimization: "
            "review and continue the saved checkpoint"
        )
    if max(optimizer["velocity_relative"].values()) > CRITERIA["optimizer_velocity_relative"]:
        failures.append(
            "Deformation fields still change: local optimizer stability is not established"
        )
    for name, row in roundtrip.items():
        if any(row[key] > CRITERIA["roundtrip_" + key] for key in ("rms", "maximum")):
            failures.append(
                f"Source-count Shooting does not reproduce {name}: "
                "runtime/state compatibility needs investigation"
            )
    for pair, subjects in integration.items():
        for name, row in subjects.items():
            if any(row[key] > CRITERIA["integration_" + key] for key in ("rms", "p95", "maximum")):
                failures.append(
                    f"Fixed-state integration differs for {name} ({pair}): "
                    "refit a finer model, then qualify that model separately"
                )
    return failures


def run(runner, *, candidate_id=None, event_callback=None, iterations=100, finer_model=False):
    root = runner.study_directory
    snapshot = study.load_reference_calibration_study(root)
    existing = declarations(study._load_events(root))
    pending = next(
        (
            e
            for e in reversed(existing)
            if not any(
                r["event"] in {"pilot_qualification_finished", "pilot_refinement_finished"}
                and r.get("candidate_id") == e["candidate"]["candidate_id"]
                for r in study._load_events(root)
            )
        ),
        None,
    )
    if pending is None:
        snapshot, identifier = prepare(
            snapshot, candidate_id=candidate_id, iterations=iterations, finer_model=finer_model
        )
        pending = declarations(study._load_events(root))[-1]
    else:
        identifier = pending["candidate"]["candidate_id"]
    source = verify_declaration(root, pending, study._load_events(root))
    if event_callback:
        event_callback(
            dict(
                event="qualification_progress",
                phase="optimizer_check",
                iterations=pending["iterations"],
            )
        )
    runner.run_current_stage(event_callback=event_callback, candidate_ids={identifier})
    snapshot = study.load_reference_calibration_study(root)
    checkpoint = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    if runner._cancel_requested or checkpoint.status != "completed":
        return snapshot
    if pending.get("refinement_timepoints"):
        study._append_event(
            root,
            "pilot_refinement_finished",
            dict(
                stage_id=snapshot.current_stage.stage_id,
                candidate_id=identifier,
                binding=study._candidate_review_binding(checkpoint),
            ),
        )
        study._append_event(
            root,
            "stage_awaiting_review",
            dict(stage_id=snapshot.current_stage.stage_id, refinement_candidate_id=identifier),
        )
        return study.load_reference_calibration_study(root)
    folder = checkpoint.config_path.parent
    source_run = study.calibration_candidate_run_directory(source)
    checkpoint_run = study.calibration_candidate_run_directory(checkpoint)
    manifest = study._verify_manifest(root)
    scales = {
        r["filename"]: float(
            np.linalg.norm(
                np.ptp(np.asarray(read_vtk_points(study._safe_study_path(root, r["copy"]))), axis=0)
            )
        )
        for r in manifest["inputs"]["subjects"]
    }
    optimizer = optimizer_check(source_run, checkpoint_run, scales, manifest["template_diagonal"])

    def objective(candidate):
        return abs(float(candidate.metrics["attachment_objective_magnitude"])) + abs(
            float(candidate.metrics["deformation_energy"])
        )

    objective_relative = abs(objective(checkpoint) - objective(source)) / max(
        objective(source), 1e-12
    )
    # Unique directory on retry: an interrupted diagnostic is never reused as a pass.
    diagnostic = folder / ("fixed-state-" + uuid4().hex)
    seed = bind_learned_seed(snapshot, identifier, diagnostic)
    config = load_config(checkpoint.config_path)
    n = int(config["model"]["deformation"]["timepoints"])
    design = dict(
        version=VERSION,
        checkpoint_binding=study._candidate_review_binding(checkpoint),
        seed=seed,
        counts=[n, 2 * n - 1, 4 * n - 3],
        criteria=pending["criteria"],
        launcher=manifest["launcher"],
    )
    study._write_json(diagnostic / "design.json", design, overwrite=False)
    grids = {}
    for count in design["counts"]:
        grids[count], _ = shoot(
            config,
            diagnostic,
            seed,
            diagnostic / str(count),
            count,
            cancelled=lambda: runner._cancel_requested,
            event_callback=event_callback,
        )
    _, recons = _reconstructions(checkpoint_run)
    roundtrip = {name: movement(recons[name], grids[n][name], scales[name]) for name in recons}
    integration = {
        f"{a}->{b}": {
            name: movement(grids[a][name], grids[b][name], scales[name]) for name in recons
        }
        for a, b in zip(design["counts"][:-1], design["counts"][1:], strict=True)
    }
    failures = failed_gates(
        optimizer,
        integration,
        roundtrip,
        converged=checkpoint.metrics["converged"],
        objective_relative=objective_relative,
        valid_geometry=checkpoint.metrics.get("invalid_face_count") == 0
        and checkpoint.metrics.get("subject_reconstruction_count")
        == snapshot.plan.pilot_subject_count,
    )
    receipt = dict(
        version=VERSION,
        candidate_id=identifier,
        declaration_event_hash=pending["event_hash"],
        checkpoint_binding=study._candidate_review_binding(checkpoint),
        criteria=dict(CRITERIA),
        optimizer=optimizer,
        objective_relative=objective_relative,
        converged=checkpoint.metrics["converged"],
        valid_geometry=checkpoint.metrics.get("invalid_face_count") == 0
        and checkpoint.metrics.get("subject_reconstruction_count")
        == snapshot.plan.pilot_subject_count,
        integration=integration,
        roundtrip=roundtrip,
        failed_gates=failures,
        numerical_pass=not failures,
        diagnostic=study._relative_path(root, diagnostic),
        artifacts={
            study._relative_path(root, p): sha256_file(p)
            for p in diagnostic.rglob("*")
            if p.is_file()
        },
        limitations=[
            "Local stability check, not gradient stationarity or global optimality.",
            "Engineering tolerances; independent scientific threshold validation remains open.",
            "Checkpoint needs fresh human anatomy approval; "
            "full-cohort confirmation remains separate.",
        ],
    )
    path = folder / ("receipt-" + uuid4().hex + ".json")
    study._write_json(path, receipt, overwrite=False)
    study._append_event(
        root,
        "pilot_qualification_finished",
        dict(
            stage_id=snapshot.current_stage.stage_id,
            candidate_id=identifier,
            receipt=study._relative_path(root, path),
            receipt_sha256=sha256_file(path),
        ),
    )
    study._append_event(
        root,
        "stage_awaiting_review",
        dict(stage_id=snapshot.current_stage.stage_id, qualification_candidate_id=identifier),
    )
    return study.load_reference_calibration_study(root)


def verified_receipts(snapshot):
    root = snapshot.study_directory
    events = study._load_events(root)
    result = {}
    for event in events:
        if event["event"] != "pilot_qualification_finished":
            continue
        path = study._safe_study_path(root, event["receipt"])
        if sha256_file(path) != event["receipt_sha256"]:
            raise ValueError("Qualification receipt changed")
        receipt = study._read_json(path, "qualification receipt")
        declaration = next(
            e for e in declarations(events) if e["event_hash"] == receipt["declaration_event_hash"]
        )
        verify_declaration(root, declaration, events)
        candidate = next(c for c in snapshot.candidates if c.candidate_id == event["candidate_id"])
        if (
            receipt["version"] != VERSION
            or receipt["criteria"] != CRITERIA
            or receipt["candidate_id"] != candidate.candidate_id
            or receipt["checkpoint_binding"] != study._candidate_review_binding(candidate)
        ):
            raise ValueError("Qualification receipt does not match its checkpoint")
        for relative, digest in receipt["artifacts"].items():
            if sha256_file(study._safe_study_path(root, relative)) != digest:
                raise ValueError("Fixed-model qualification artifact changed")
        failures = failed_gates(
            receipt["optimizer"],
            receipt["integration"],
            receipt["roundtrip"],
            converged=receipt["converged"],
            objective_relative=receipt["objective_relative"],
            valid_geometry=receipt["valid_geometry"],
        )
        expected_subjects = {s.filename for s in snapshot.plan.selected_pilot_subjects}
        n = int(load_config(candidate.config_path)["model"]["deformation"]["timepoints"])
        if (
            receipt["failed_gates"] != failures
            or receipt["numerical_pass"] != (not failures)
            or set(receipt["roundtrip"]) != expected_subjects
            or set(receipt["optimizer"]["subjects"]) != expected_subjects
            or set(receipt["optimizer"]["velocity_relative"]) != expected_subjects
            or set(receipt["integration"]) != {f"{n}->{2 * n - 1}", f"{2 * n - 1}->{4 * n - 3}"}
            or any(set(rows) != expected_subjects for rows in receipt["integration"].values())
        ):
            raise ValueError("Qualification gates or complete-cohort evidence changed")
        result[candidate.candidate_id] = receipt
    return result


def verify_completed(root, plan, events):
    """A completed report is usable only while the qualification bytes stay bound."""
    from diffeoforge.reference_stage_retention import _candidate

    ids = {e["candidate_id"] for e in events if e["event"] == "pilot_qualification_finished"}
    if not ids:
        return
    candidates = tuple(
        _candidate(root, plan.stages[-1].stage_id, identifier)[0] for identifier in sorted(ids)
    )
    snapshot = study.ReferenceCalibrationStudySnapshot(
        root,
        "qualification-verification",
        plan,
        "awaiting_review",
        plan.stages[-1],
        candidates,
        {},
        {},
        len(events),
        None,
        None,
        None,
    )
    verified_receipts(snapshot)


def assess(snapshot, base):
    receipts = verified_receipts(snapshot)
    rows = []
    for c in snapshot.candidates:
        receipt = receipts.get(c.candidate_id)
        reasons = (
            list(receipt["failed_gates"])
            if receipt
            else ["Run the independent saved-model qualification"]
        )
        if snapshot.visual_reviews.get(c.candidate_id) is False:
            reasons.append("Anatomical review rejected: improve this saved fit")
        elif receipt and snapshot.visual_reviews.get(c.candidate_id) is not True:
            reasons.append("Review the new checkpoint and record anatomical approval")
        rows.append(
            CalibrationCandidateAssessment(
                c.candidate_id, not reasons, not reasons, None, None, None, None, tuple(reasons)
            )
        )
    winner = next((r.candidate_id for r in reversed(rows) if r.eligible), None)
    assessment = replace(
        base,
        version=VERSION,
        fingerprint="",
        candidates=tuple(rows),
        status="recommendation_ready" if winner else "needs_review_or_qualification",
        balanced_candidate_id=winner,
        independent_rank_candidate_id=winner,
        recommendation_confidence="qualified_and_visually_approved" if winner else "not_qualified",
        automatic_selection_allowed=False,
        weight_stability=None,
        subject_bootstrap_stability=None,
        score_margin=None,
        metric_weights=(),
        pareto_candidate_ids=(winner,) if winner else (),
        cautions=(
            "Optimizer stability and fixed-state integration are checked separately.",
            "Passing this pilot does not establish global optimality or biological validity.",
        ),
    )
    return replace(assessment, fingerprint=study._canonical_hash(assessment.as_manifest()))


def export_audit(directory, destination):
    """Export verified search lineage and decisions, without copying private meshes."""
    snapshot = study.load_reference_calibration_study(directory)
    root = snapshot.study_directory
    lineage = []
    for _ in range(64):
        manifest = study._verify_manifest(root)
        lineage.append(
            dict(
                study_directory=str(root),
                manifest_sha256=sha256_file(root / study.STUDY_MANIFEST),
                manifest=manifest,
                events=list(study._load_events(root)),
            )
        )
        parent = manifest.get("search_extension_source", {}).get("study_directory")
        if not parent:
            break
        root = Path(parent).resolve()
    else:
        raise ValueError("Pilot audit lineage exceeds supported depth")
    series_root, _ = study._search_extension_series(snapshot.study_directory)
    sequence = None
    sequence_source = None
    individual_trials = []
    sequence_info = (
        study._verify_manifest(snapshot.study_directory).get("fit_search", {}).get("sequence")
    )
    if sequence_info:
        from diffeoforge.reference_sequential_fit import _read

        sequence_root = Path(sequence_info["root"]).resolve()
        sequence = _read(sequence_root)
        sequence_source = dict(
            study_directory=str(sequence_root),
            manifest=study._verify_manifest(sequence_root),
            manifest_sha256=sha256_file(sequence_root / study.STUDY_MANIFEST),
            events=list(study._load_events(sequence_root)),
        )
        for relative in sequence.get("trials", []):
            child = (sequence_root / relative).resolve()
            if not child.is_relative_to(sequence_root):
                raise ValueError("Audit trial leaves its saved sequence")
            study.load_reference_calibration_study(child)
            review_root, _ = study._search_extension_series(child)
            individual_trials.append(
                dict(
                    study_directory=str(child),
                    manifest=study._verify_manifest(child),
                    manifest_sha256=sha256_file(child / study.STUDY_MANIFEST),
                    events=list(study._load_events(child)),
                    reviews=list(study._read_review_journal(review_root)),
                )
            )
    qualification = (
        verified_receipts(snapshot)
        if snapshot.current_stage and snapshot.current_stage.order == 4
        else {
            r["candidate_id"]: r
            for r in study.load_reference_calibration_report(snapshot.study_directory).get(
                "numerical_qualification", []
            )
        }
        if snapshot.status == "completed"
        else {}
    )
    from diffeoforge import reference_pilot_completion as completion

    report = (
        study.load_reference_calibration_report(snapshot.study_directory)
        if snapshot.status == "completed"
        else {}
    )
    saved_checks = (
        completion.evidence(snapshot)
        if snapshot.current_stage and snapshot.current_stage.order == 4
        else report.get("saved_model_integration_checks", [])
    )
    payload = dict(
        version=VERSION,
        status=snapshot.status,
        lineage=lineage,
        reviews=list(study._read_review_journal(series_root)),
        selected_values=dict(snapshot.selected_values),
        selected_candidates=dict(snapshot.selected_candidate_ids),
        qualification=qualification,
        saved_model_integration_checks=saved_checks,
        final_pilot_completion=report.get("final_pilot_completion"),
        specimen_sequence=sequence,
        specimen_sequence_source=sequence_source,
        individual_trials=individual_trials,
        scientific_boundary="Pilot evidence and human decisions; "
        "no guarantee of global optimum or biological validity",
    )
    destination = Path(destination).resolve()
    study._write_json(destination, payload, overwrite=False)
    return destination
