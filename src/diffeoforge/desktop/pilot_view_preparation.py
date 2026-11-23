"""Bound pilot presentation prepared away from the GUI event loop."""

from dataclasses import dataclass
from pathlib import Path

from diffeoforge import reference_calibration_study as study


@dataclass(frozen=True)
class PilotView:
    snapshot: study.ReferenceCalibrationStudySnapshot
    manifest: dict
    assessment: object
    fits: dict
    provisional_ids: frozenset[str]
    report: dict | None
    sequence_info: dict | None
    sequence_progress: dict | None
    density_rows: tuple | None
    guidance: dict | None = None


def prepare_pilot_view(directory: Path, snapshot=None) -> PilotView:
    """Read-only presentation; dispatch still performs its own fresh verification."""
    from diffeoforge.reference_sequential_fit import sequence_info, sequence_progress

    root = Path(directory).resolve()
    with study.calibration_verification_scope():
        snapshot = snapshot or study.load_reference_calibration_study(root)
        if snapshot.study_directory.resolve() != root:
            raise ValueError("Pilot presentation belongs to a different study")
        manifest = study._read_json(root / study.STUDY_MANIFEST, "study")
        assessment = None
        provisional = set()
        stage = snapshot.current_stage
        if snapshot.status == "awaiting_review":
            assessment = study.assess_reference_calibration_snapshot(
                snapshot, visual_approvals=snapshot.visual_reviews,
                completion_preview=bool(stage and stage.order == 4),
            )
        if stage and stage.order != 4:
            provisional = {
                c.candidate_id for c in snapshot.candidates
                if study.iteration_limit_selection_available(snapshot, c.candidate_id)
            }
        fits = {
            c.candidate_id: study.normalized_candidate_subject_fit(snapshot, c)
            for c in snapshot.candidates if c.metrics is not None
        }
        report = (
            study.load_reference_calibration_report(root)
            if snapshot.report_json_path is not None else None
        )
        density_rows = None
        if manifest.get("control_density"):
            from diffeoforge.reference_control_density import rows

            density_rows = tuple(rows(snapshot))
        return PilotView(
            snapshot, manifest, assessment, fits, frozenset(provisional), report,
            sequence_info(root), sequence_progress(root), density_rows,
            _guidance(snapshot, manifest),
        )


def _guidance(snapshot, manifest):
    from diffeoforge.guided_strategy import prepare_proposals, state
    from diffeoforge.reference_guided_pilot import record

    info = record(snapshot)
    if info and snapshot.current_stage and snapshot.current_stage.order == 1:
        from diffeoforge.pilot_input_topology import prepare_for_snapshot

        context = state(snapshot)
        from diffeoforge.reference_guard_failure import for_candidate
        from diffeoforge.reference_qualification_resume import pending

        context['qualification_pending'] = pending(snapshot)
        context["guard_failures"] = {
            c.candidate_id: failure for c in snapshot.candidates
            if c.candidate_id not in context['qualification_pending']
            and c.candidate_id not in context.get("common_stage_failures", {})
            if (failure := for_candidate(c)) is not None
        }
        context["input_topology"] = prepare_for_snapshot(snapshot, manifest)
        result = prepare_proposals(snapshot, context)
        result["prepared_start_note"] = _prepared_start_note(snapshot, info)
        from diffeoforge.pilot_adaptive_run import presentation as adaptive_presentation

        result['bounded_adaptive'] = adaptive_presentation(snapshot)
        result['qualification_pending'] = context['qualification_pending']
        declaration = snapshot.attachment_comparison.get('regional_objective')
        if declaration:
            from diffeoforge.pilot_region_scope import summary
            from diffeoforge.regional_fit import read_plan

            result['regional_scope'] = summary(read_plan(dict(project=dict(
                parameter_provenance=dict(regional_fit=declaration)))))
        return result
    return None


def _prepared_start_note(snapshot, info):
    """Describe the prepared specimen's bound field independently of its settings."""
    from diffeoforge.desktop.saved_fit_comparison import trial_label
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.guided_fit_direction import local_quality_note
    from diffeoforge.pilot_common_diagnosis import accepted_reference

    goal, target = info.get("goal"), info.get("target")
    if goal not in {"shared_check", "next_form", "form_model_check"} or not target:
        return ""
    strategy = info.get("strategy") or {}
    ledger = strategy.get("form_progress")
    refinement = snapshot.attachment_comparison.get("refinement") or {}
    if info["phase"] == "validate" and goal in {"next_form", "form_model_check"}:
        if not ledger or refinement or strategy.get("common_multiscale"):
            return ""
        protocol_ref = ledger["protocol"]["reference"]
        return (f"{target} starts from the template with zero initial momenta. "
                f"It uses the shared settings and control grid from {protocol_ref['target']}. "
                "Review the fit on this specimen.")

    seed = refinement.get("reference")
    approved = (strategy.get("shared_model_check") or {}).get("reference")
    if goal == "form_model_check" and ledger:
        approved = accepted_reference(ledger, target)
    if (not seed or seed != approved or seed["target"] != target
            or refinement.get("initialization") not in {"learned", "nested"}):
        return ""
    source = verify_reference(seed)
    if source.visual_reviews.get(seed["candidate_id"]) is not True:
        return ""
    candidate = next(c for c in source.candidates if c.candidate_id == seed["candidate_id"])
    note = (f"{target} starts from its approved individual fit, {trial_label(source, candidate)}. "
            "Its saved momenta initialize the deformation. ")
    if refinement["initialization"] == "nested":
        note += "Additional control points start with zero momentum. "
    note += "The optimizer starts a new history. Review the resulting common fit separately."
    warnings = local_quality_note(source, seed)
    return note + (" " + warnings if warnings else "")
