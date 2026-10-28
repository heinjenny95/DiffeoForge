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

    if record(snapshot) and snapshot.current_stage and snapshot.current_stage.order == 1:
        from diffeoforge.pilot_input_topology import prepare_for_snapshot

        context = state(snapshot)
        from diffeoforge.reference_guard_failure import for_candidate

        context["guard_failures"] = {
            c.candidate_id: failure for c in snapshot.candidates
            if (failure := for_candidate(c)) is not None
        }
        context["input_topology"] = prepare_for_snapshot(snapshot, manifest)
        return prepare_proposals(snapshot, context)
    return None
