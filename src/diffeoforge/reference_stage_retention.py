"""Explicit reuse of an unchanged, previously approved pilot reconstruction."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from diffeoforge.reference_calibration import CalibrationCandidate

VERSION = "retained-approved-stage-v1"


def _values(config):
    deformation = config["model"]["deformation"]
    return {
        "attachment_kernel_width": config["model"]["attachment"]["kernel_width"],
        "deformation_kernel_width": deformation["kernel_width"],
        "initial_control_point_spacing": deformation["initial_control_point_spacing"],
        "noise_std": config["model"]["noise_std"],
        "timepoints": deformation["timepoints"],
    }


def _candidate(root, stage_id, candidate_id):
    from diffeoforge import reference_calibration_study as study

    events = study._load_events(root)
    completed = next(
        (
            e
            for e in reversed(events)
            if e["event"] == "candidate_completed"
            and e.get("stage_id") == stage_id
            and e.get("candidate_id") == candidate_id
        ),
        None,
    )
    if completed is None:
        raise study.ReferenceCalibrationStudyError("Previous approved fit evidence is absent")
    prepared = study._prepared_candidates(root, events, stage_id)[candidate_id]
    candidate = study.CalibrationStudyCandidateState(
        candidate_id,
        "Previously approved fit",
        "completed",
        study._safe_study_path(root, prepared["config"]),
        study._safe_study_path(root, completed["run_directory"]),
        completed["metrics"],
        None,
        int(completed.get("attempt", 1)),
    )
    return candidate, completed


def _previous(snapshot):
    from diffeoforge import reference_calibration_study as study

    stage = snapshot.current_stage
    if stage is None or stage.order not in (2, 3):
        raise study.ReferenceCalibrationStudyError("Retaining a fit applies to stages 2 and 3")
    previous_id = snapshot.plan.stages[stage.order - 2].stage_id
    root = snapshot.study_directory
    for _ in range(64):
        events = study._load_events(root)
        selection = next(
            (
                e
                for e in reversed(events)
                if e["event"] == "stage_selected" and e.get("stage_id") == previous_id
            ),
            None,
        )
        if selection is None:
            raise study.ReferenceCalibrationStudyError("Previous stage has no recorded selection")
        candidate_id = selection["candidate_id"]
        if any(
            e["event"] == "candidate_completed"
            and e.get("stage_id") == previous_id
            and e.get("candidate_id") == candidate_id
            for e in events
        ):
            candidate, completed = _candidate(root, previous_id, candidate_id)
            return root, selection, candidate, completed
        parent = study._verify_manifest(root).get("search_extension_source", {})
        if not parent.get("study_directory"):
            break
        root = Path(parent["study_directory"]).resolve()
    raise study.ReferenceCalibrationStudyError("Previous fit lineage cannot be resolved")


def verify_reference(root, record):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file

    source = record["retained_source"]
    if source.get("version") != VERSION:
        raise study.ReferenceCalibrationStudyError("Unknown retained-fit protocol")
    source_root = Path(source["study_directory"]).resolve()
    source_manifest = study._verify_manifest(source_root)
    current_manifest = study._read_json(root / study.STUDY_MANIFEST, "study")
    if (
        sha256_file(source_root / study.STUDY_MANIFEST) != source["manifest_sha256"]
        or source_manifest["inputs"]["subjects"] != current_manifest["inputs"]["subjects"]
    ):
        raise study.ReferenceCalibrationStudyError("Retained fit cohort or manifest changed")
    stages = [s["stage_id"] for s in current_manifest["plan"]["stages"]]
    if stages.index(source["stage_id"]) + 1 != stages.index(record["stage_id"]):
        raise study.ReferenceCalibrationStudyError(
            "Retained fit must come from the preceding stage"
        )
    events = study._load_events(source_root)
    selection = next((e for e in events if e["event_hash"] == source["selection_event_hash"]), None)
    candidate, completed = _candidate(source_root, source["stage_id"], source["candidate_id"])
    if (
        selection is None
        or selection.get("event") != "stage_selected"
        or selection.get("stage_id") != source["stage_id"]
        or selection.get("candidate_id") != source["candidate_id"]
        or selection.get("visual_approvals", {}).get(source["candidate_id"]) is not True
        or completed["event_hash"] != source["completed_event_hash"]
        or candidate.metrics != record["metrics"]
        or study._candidate_review_binding(candidate) != source["binding"]
        or record["candidate"]["parameter_values"] != _values(load_config(candidate.config_path))
    ):
        raise study.ReferenceCalibrationStudyError(
            "Retained fit differs from its approved evidence"
        )
    series_root, _ = study._search_extension_series(source_root)
    reviews = events + study._read_review_journal(series_root)
    decisions = study._load_candidate_reviews(reviews, source["stage_id"], (candidate,))
    if decisions.get(candidate.candidate_id) is False:
        raise study.ReferenceCalibrationStudyError("Previous fit approval has been withdrawn")
    if decisions.get(candidate.candidate_id) is not True:
        earlier = next(
            (
                e
                for e in events
                if e["event"] == "stage_retained"
                and e.get("stage_id") == source["stage_id"]
                and e["candidate"]["candidate_id"] == candidate.candidate_id
            ),
            None,
        )
        if earlier is None:
            raise study.ReferenceCalibrationStudyError("Previous fit has no bound visual approval")
        verify_reference(source_root, earlier)
    return candidate


def overlay_plan(plan, events):
    """The append-only event binds additions; the original plan remains immutable."""
    from diffeoforge.reference_calibration import _canonical_hash

    changed = False
    for event in events:
        if event["event"] != "stage_retained":
            continue
        stage_id = event["stage_id"]
        declaration = event["candidate"]
        candidate = CalibrationCandidate(
            declaration["candidate_id"],
            declaration["label"],
            tuple(sorted(declaration["parameter_values"].items())),
            declaration["rationale"],
        )
        if candidate.candidate_id != stage_id + "-retained":
            raise ValueError("Invalid retained candidate identity")
        stages = []
        for stage in plan.stages:
            if stage.stage_id == stage_id:
                if any(c.candidate_id == candidate.candidate_id for c in stage.candidates):
                    raise ValueError("Retained fit was registered more than once")
                stage = replace(stage, candidates=(*stage.candidates, candidate))
            stages.append(stage)
        plan = replace(plan, stages=tuple(stages))
        changed = True
    if changed:
        payload = plan.provenance
        for name in ("fingerprint", "status", "pilot_subject_count"):
            payload.pop(name)
        plan = replace(plan, fingerprint=_canonical_hash(payload))
    return plan


def register_previous_fit(snapshot):
    """Register read-only evidence, without a fit, new QC approval or old-file edits."""
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file

    root = snapshot.study_directory
    stage = snapshot.current_stage
    if stage is None:
        raise study.ReferenceCalibrationStudyError("No current stage")
    candidate_id = stage.stage_id + "-retained"
    if any(c.candidate_id == candidate_id for c in snapshot.candidates):
        return snapshot
    if any(c.status == "orphaned" for c in snapshot.candidates):
        raise study.ReferenceCalibrationStudyError("Wait for the active candidate to finish")
    source_root, selection, candidate, completed = _previous(snapshot)
    config = copy.deepcopy(load_config(candidate.config_path))
    for field in ("directory", "template"):
        config["input"][field] = str(
            (candidate.config_path.parent / config["input"][field]).resolve()
        )
    deformation = config["model"]["deformation"]
    for field in ("initial_control_points", "initial_momenta"):
        if deformation.get(field):
            deformation[field] = str((candidate.config_path.parent / deformation[field]).resolve())
    values = _values(config)
    declaration = CalibrationCandidate(
        candidate_id,
        "Keep previously approved fit",
        tuple(sorted(values.items())),
        "Unchanged saved reconstruction and prior anatomical approval; no new optimization.",
    )
    record = dict(
        study_directory=str(root),
        stage_id=stage.stage_id,
        candidate=declaration.as_manifest(),
        metrics=dict(candidate.metrics),
        retained_source=dict(
            version=VERSION,
            study_directory=str(source_root),
            stage_id=selection["stage_id"],
            candidate_id=candidate.candidate_id,
            manifest_sha256=sha256_file(source_root / study.STUDY_MANIFEST),
            selection_event_hash=selection["event_hash"],
            completed_event_hash=completed["event_hash"],
            binding=study._candidate_review_binding(candidate),
        ),
    )
    verify_reference(root, record)  # Check before writing any candidate/event.
    directory = root / "retained-fits" / stage.stage_id
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "atlas.yaml"
    study._write_yaml(config_path, config, overwrite=False)
    record.update(
        config=study._relative_path(root, config_path), config_sha256=sha256_file(config_path)
    )
    study._write_json(directory / "evidence.json", record, overwrite=False)
    record.update(
        evidence=study._relative_path(root, directory / "evidence.json"),
        evidence_sha256=sha256_file(directory / "evidence.json"),
    )
    study._append_event(root, "stage_retained", record)
    study._append_event(
        root,
        "candidate_completed",
        dict(
            stage_id=stage.stage_id,
            candidate_id=candidate_id,
            attempt=0,
            run_directory=study._relative_path(root, directory),
            metrics=record["metrics"],
            retained=True,
        ),
    )
    return study.load_reference_calibration_study(root)


def keep_previous_fit(directory):
    from diffeoforge import reference_calibration_study as study

    snapshot = register_previous_fit(study.load_reference_calibration_study(directory))
    return study._record_reference_calibration_stage_selection(
        directory,
        visual_approvals={},
        selected_candidate_id=snapshot.current_stage.stage_id + "-retained",
        selection_mode="researcher_retained_approved_fit",
        selection_reason=(
            "Researcher kept the exact previously approved fit. No new fit or QC approval."
        ),
    )[0]
