"""Saved-model completion with separate optimizer, integration and anatomy evidence.

Legacy qualification receipts keep their declared meaning. State-change measures
are diagnostics, not universal scientific stopping rules. A capped model can only
be selected explicitly and provisionally, with verified integration and fresh QC.
"""

from dataclasses import replace
from uuid import uuid4

import numpy as np

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_pilot_qualification as legacy
from diffeoforge.config import load_config
from diffeoforge.mesh import read_vtk_points, sha256_file
from diffeoforge.reference_calibration import CalibrationCandidateAssessment
from diffeoforge.reference_fixed_shooting import movement, shoot

VERSION = "saved-model-completion-v1"
CRITERIA = {
    k: v for k, v in legacy.CRITERIA.items() if k.startswith(("integration_", "roundtrip_"))
}


def integration_failures(receipt):
    failures = []
    if receipt.get("valid_geometry") is not True:
        failures.append("Geometry or complete-cohort evidence is invalid")
    for group, rows in (
        ("roundtrip", receipt["roundtrip"]),
        ("integration", receipt["integration"]),
    ):
        groups = {"source": rows} if group == "roundtrip" else rows
        keys = ("rms", "maximum") if group == "roundtrip" else ("rms", "p95", "maximum")
        for pair, subjects in groups.items():
            for name, values in subjects.items():
                for key in keys:
                    value = values[key]
                    if isinstance(value, bool) or not np.isfinite(value) or value < 0:
                        raise ValueError("Integration evidence must be finite and nonnegative")
                    if value > receipt["criteria"][group + "_" + key]:
                        failures.append(
                            f"{group} check differs for {name} ({pair}): inspect/refine"
                        )
    return failures


def evidence(snapshot):
    """Verify original receipts; reuse their fixed-state checks without rewriting them."""
    root = snapshot.study_directory
    events = study._load_events(root)
    receipts = legacy.verified_receipts(snapshot)
    records = {e["candidate_id"]: e for e in events if e["event"] == "pilot_qualification_finished"}
    for event in events:
        if event["event"] != "pilot_integration_check_finished":
            continue
        path = study._safe_study_path(root, event["receipt"])
        if sha256_file(path) != event["receipt_sha256"]:
            raise ValueError("Saved-model integration receipt changed")
        receipt = study._read_json(path, "integration receipt")
        declaration = next(
            e for e in events if e["event_hash"] == receipt["declaration_event_hash"]
        )
        candidate = next(c for c in snapshot.candidates if c.candidate_id == event["candidate_id"])
        binding = study._candidate_review_binding(candidate)
        n = int(load_config(candidate.config_path)["model"]["deformation"]["timepoints"])
        names = {s.filename for s in snapshot.plan.selected_pilot_subjects}
        if (
            receipt["version"] != VERSION
            or declaration["event"] != "pilot_integration_check_declared"
            or declaration["version"] != VERSION
            or declaration["candidate_id"] != candidate.candidate_id
            or declaration["binding"] != binding
            or receipt["checkpoint_binding"] != binding
            or declaration["criteria"] != CRITERIA
            or receipt["criteria"] != CRITERIA
            or declaration["counts"] != [n, 2 * n - 1, 4 * n - 3]
            or set(receipt["roundtrip"]) != names
            or set(receipt["integration"]) != {f"{n}->{2 * n - 1}", f"{2 * n - 1}->{4 * n - 3}"}
            or any(set(rows) != names for rows in receipt["integration"].values())
            or receipt["valid_geometry"] != _valid(candidate, snapshot)
        ):
            raise ValueError("Saved-model integration identity or complete cohort changed")
        for relative, digest in receipt["artifacts"].items():
            if sha256_file(study._safe_study_path(root, relative)) != digest:
                raise ValueError("Saved-model integration artifact changed")
        if receipt["integration_pass"] != (not integration_failures(receipt)):
            raise ValueError("Saved-model integration decision changed")
        receipts[candidate.candidate_id] = receipt
        records[candidate.candidate_id] = event
    return {
        identifier: dict(
            receipt=value,
            receipt_path=records[identifier]["receipt"],
            receipt_sha256=records[identifier]["receipt_sha256"],
            failures=integration_failures(value),
        )
        for identifier, value in receipts.items()
    }


def _valid(candidate, snapshot):
    m = candidate.metrics or {}
    return bool(
        candidate.status == "completed"
        and m.get("completed") is True
        and type(m.get("invalid_face_count")) is int
        and m["invalid_face_count"] == 0
        and m.get("fit_scope") in (None, "full_targets")
        and type(m.get("subject_reconstruction_count")) is int
        and m.get("subject_reconstruction_count") == snapshot.plan.pilot_subject_count
    )


def capped(candidate):
    m = candidate.metrics or {}
    return bool(
        m.get("converged") is False
        and m.get("optimizer_stop_signal") == "maximum_iterations"
        and type(m.get("maximum_iterations")) is int
        and m["maximum_iterations"] > 0
        and type(m.get("final_iteration")) is int
        and m["final_iteration"] >= m["maximum_iterations"]
    )


def provisional_available(snapshot, identifier, *, checked=None):
    if not snapshot.current_stage or snapshot.current_stage.order != 4:
        return False
    candidate = next((c for c in snapshot.candidates if c.candidate_id == identifier), None)
    checked = evidence(snapshot) if checked is None else checked
    return bool(
        candidate
        and _valid(candidate, snapshot)
        and capped(candidate)
        and identifier in checked
        and not checked[identifier]["failures"]
        and snapshot.visual_reviews.get(identifier) is not False
    )


def assess(snapshot, base):
    checked = evidence(snapshot)
    rows = []
    for c in snapshot.candidates:
        reasons = (
            list(checked[c.candidate_id]["failures"])
            if c.candidate_id in checked
            else ["Check time resolution of this saved fit (no optimization)"]
        )
        if not _valid(c, snapshot):
            reasons.append("A complete, valid joint fit is required")
        if (c.metrics or {}).get("converged") is not True:
            reasons.append(
                "Iteration limit reached: explicit provisional finish is available after QC"
                if provisional_available(snapshot, c.candidate_id, checked=checked)
                else "Optimizer convergence is not established"
            )
        if snapshot.visual_reviews.get(c.candidate_id) is not True:
            reasons.append(
                "Anatomical review rejected"
                if snapshot.visual_reviews.get(c.candidate_id) is False
                else "Review the saved joint fit and record approval"
            )
        rows.append(
            CalibrationCandidateAssessment(
                c.candidate_id, not reasons, not reasons, None, None, None, None, tuple(reasons)
            )
        )
    # Choose the smallest checked count. At equal count prefer the latest saved
    # state; never label a capped state an automatic recommendation.
    definitions = {c.candidate_id: c for c in snapshot.current_stage.candidates}
    eligible = [r for r in rows if r.eligible]
    winner = (
        min(
            eligible,
            key=lambda r: (
                definitions[r.candidate_id].values["timepoints"],
                -next(
                    i for i, c in enumerate(snapshot.candidates) if c.candidate_id == r.candidate_id
                ),
            ),
        ).candidate_id
        if eligible
        else None
    )
    result = replace(
        base,
        version=VERSION,
        fingerprint="",
        candidates=tuple(rows),
        status="recommendation_ready" if winner else "needs_review_or_check",
        balanced_candidate_id=winner,
        independent_rank_candidate_id=winner,
        recommendation_confidence="native_convergence_integration_and_QC"
        if winner
        else "not_qualified",
        automatic_selection_allowed=False,
        weight_stability=None,
        subject_bootstrap_stability=None,
        score_margin=None,
        metric_weights=(),
        pareto_candidate_ids=(winner,) if winner else (),
        cautions=(
            "Native optimizer convergence, fixed-state integration and anatomy are separate.",
            "State movement/objective/velocity changes are sensitivity diagnostics, "
            "not accuracy limits.",
            "Provisional completion does not establish stable momenta or biological validity.",
        ),
    )
    return replace(result, fingerprint=study._canonical_hash(result.as_manifest()))


def run(runner, *, candidate_id=None, event_callback=None):
    """Check a fixed saved state, with no atlas fitting or optimizer continuation."""
    from diffeoforge.reference_adaptive_calibration import bind_learned_seed

    snapshot = study.load_reference_calibration_study(runner.study_directory)
    if not snapshot.current_stage or snapshot.current_stage.order != 4:
        raise ValueError("Saved-model integration checks belong to Stage 4")
    events = study._load_events(snapshot.study_directory)
    if any(
        not any(
            r["event"] in {"pilot_qualification_finished", "pilot_refinement_finished"}
            and r.get("candidate_id") == e["candidate"]["candidate_id"]
            for r in events
        )
        for e in legacy.declarations(events)
    ):
        # An already declared calculation keeps its original settings and identity.
        return legacy.run(runner, candidate_id=candidate_id, event_callback=event_callback)
    if not snapshot.candidates or not any(c.metrics for c in snapshot.candidates):
        from diffeoforge.reference_stage_retention import register_previous_fit

        snapshot = register_previous_fit(snapshot, for_qualification=True)
    candidates = [
        c
        for c in snapshot.candidates
        if _valid(c, snapshot)
        and snapshot.visual_reviews.get(c.candidate_id) is not False
        and (candidate_id is None or c.candidate_id == candidate_id)
    ]
    if not candidates:
        raise ValueError("Choose a complete joint fit that has not been rejected")
    source = max(
        candidates,
        key=lambda c: (
            snapshot.visual_reviews.get(c.candidate_id) is True,
            snapshot.candidates.index(c),
        ),
    )
    if source.candidate_id in evidence(snapshot):
        if event_callback:
            event_callback(dict(event="qualification_progress", phase="integration_cached"))
        return snapshot
    root = snapshot.study_directory
    folder = root / "integration-checks" / uuid4().hex
    seed = bind_learned_seed(snapshot, source.candidate_id, folder)
    config = load_config(source.config_path)
    n = int(config["model"]["deformation"]["timepoints"])
    study._append_event(
        root,
        "pilot_integration_check_declared",
        dict(
            version=VERSION,
            candidate_id=source.candidate_id,
            binding=study._candidate_review_binding(source),
            criteria=dict(CRITERIA),
            counts=[n, 2 * n - 1, 4 * n - 3],
        ),
    )
    declaration = study._load_events(root)[-1]
    manifest = study._verify_manifest(root)
    scales = {
        r["filename"]: float(
            np.linalg.norm(
                np.ptp(np.asarray(read_vtk_points(study._safe_study_path(root, r["copy"]))), axis=0)
            )
        )
        for r in manifest["inputs"]["subjects"]
    }
    grids = {}
    for count in declaration["counts"]:
        grids[count], _ = shoot(
            config,
            folder,
            seed,
            folder / str(count),
            count,
            cancelled=lambda: runner._cancel_requested,
            event_callback=event_callback,
        )
    _, recons = legacy._reconstructions(study.calibration_candidate_run_directory(source))
    receipt = dict(
        version=VERSION,
        checkpoint_binding=declaration["binding"],
        declaration_event_hash=declaration["event_hash"],
        criteria=dict(CRITERIA),
        valid_geometry=_valid(source, snapshot),
        roundtrip={name: movement(recons[name], grids[n][name], scales[name]) for name in recons},
        integration={
            f"{a}->{b}": {
                name: movement(grids[a][name], grids[b][name], scales[name]) for name in recons
            }
            for a, b in zip(declaration["counts"][:-1], declaration["counts"][1:], strict=True)
        },
        artifacts={
            study._relative_path(root, p): sha256_file(p) for p in folder.rglob("*") if p.is_file()
        },
    )
    receipt["integration_pass"] = not integration_failures(receipt)
    path = folder / "receipt.json"
    study._write_json(path, receipt, overwrite=False)
    study._append_event(
        root,
        "pilot_integration_check_finished",
        dict(
            candidate_id=source.candidate_id,
            receipt=study._relative_path(root, path),
            receipt_sha256=sha256_file(path),
        ),
    )
    study._append_event(
        root, "stage_awaiting_review", dict(stage_id=snapshot.current_stage.stage_id)
    )
    return study.load_reference_calibration_study(root)


def decision(snapshot, identifier):
    checked = evidence(snapshot)
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    record = checked.get(identifier)
    if not record or record["failures"] or not _valid(candidate, snapshot):
        raise ValueError("Valid complete-cohort and fixed-state integration evidence is required")
    if snapshot.visual_reviews.get(identifier) is not True:
        raise ValueError("Review this exact saved joint fit before finishing")
    converged = candidate.metrics.get("converged") is True
    if not converged and not capped(candidate):
        raise ValueError("Only a fit stopped at its iteration cap can finish provisionally")
    return dict(
        version=VERSION,
        converged=converged,
        provisional=not converged,
        binding=study._candidate_review_binding(candidate),
        receipt=record["receipt_path"],
        receipt_sha256=record["receipt_sha256"],
        legacy_numerical_pass=record["receipt"].get("numerical_pass"),
        limitation="Pilot completion permits a new full-cohort atlas; "
        "it is not final atlas approval. "
        "A capped pilot does not establish optimizer stability or stable momenta.",
    )


def finish(directory, identifier):
    snapshot = study.load_reference_calibration_study(directory)
    if snapshot.status == "completed":
        if snapshot.selected_candidate_ids.get(snapshot.plan.stages[-1].stage_id) != identifier:
            raise ValueError("This pilot is already finished with a different saved fit")
        return snapshot, None
    selected = decision(snapshot, identifier)
    return study._record_reference_calibration_stage_selection(
        directory,
        visual_approvals={},
        selected_candidate_id=identifier,
        selection_mode="researcher_final_provisional"
        if selected["provisional"]
        else "researcher_saved_model_completion",
        selection_reason="Researcher selected a reviewed fixed-state model under "
        "separate optimizer, "
        "integration and anatomy checks. Original qualification receipts are unchanged. "
        + selected["limitation"],
    )


def verify_final_decision(root, plan, events):
    selections = [
        e for e in events if e["event"] == "stage_selected" and e.get("final_pilot_completion")
    ]
    if not selections:
        return
    from diffeoforge.reference_stage_retention import _candidate

    identifiers = {
        e["candidate_id"]
        for e in events
        if e["event"] == "candidate_completed" and e.get("stage_id") == plan.stages[-1].stage_id
    }
    candidates = tuple(
        _candidate(root, plan.stages[-1].stage_id, c)[0] for c in sorted(identifiers)
    )
    # Desktop preview QC uses the separate atomic review journal so it can run
    # while an engine owns the main event ledger. Verify the same bound reviews
    # on completion/reopening as the ordinary study loader, without inventing QC
    # from the selection event's summary.
    series_root, _ = study._search_extension_series(root)
    reviews = tuple(
        r
        for r in study._read_review_journal(series_root)
        if r.get("stage_id") == plan.stages[-1].stage_id
        and r.get("candidate_id") in identifiers
    )
    for event in selections:
        earlier = tuple(e for e in events if e["sequence"] < event["sequence"])
        snapshot = study.ReferenceCalibrationStudySnapshot(
            root,
            "completion-verification",
            plan,
            "awaiting_review",
            plan.stages[-1],
            candidates,
            {},
            {},
            len(earlier),
            None,
            None,
            None,
            visual_reviews=study._load_candidate_reviews(
                earlier + reviews, plan.stages[-1].stage_id, candidates
            ),
        )
        expected = decision(snapshot, event["candidate_id"])
        if (
            event["stage_id"] != plan.stages[-1].stage_id
            or event["final_pilot_completion"] != expected
        ):
            raise ValueError("Final pilot completion evidence changed")
        mode = (
            "researcher_final_provisional"
            if expected["provisional"]
            else "researcher_saved_model_completion"
        )
        if event["selection_mode"] != mode:
            raise ValueError("Final pilot completion mode changed")


def verify_checks(root, plan, events):
    if not any(e["event"] == "pilot_integration_check_finished" for e in events):
        return
    from diffeoforge.reference_stage_retention import _candidate

    identifiers = {
        e["candidate_id"]
        for e in events
        if e["event"] == "candidate_completed" and e.get("stage_id") == plan.stages[-1].stage_id
    }
    candidates = tuple(
        _candidate(root, plan.stages[-1].stage_id, c)[0] for c in sorted(identifiers)
    )
    snapshot = study.ReferenceCalibrationStudySnapshot(
        root,
        "integration-verification",
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
    evidence(snapshot)
