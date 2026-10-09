"""Persistent human-reviewed singleton filters for joint pilot stages 2 and 3.

Probes freeze the candidate's learned reference and control basis. Their fields
never seed or replace joint results, and their approval never advances a stage.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config, validate_input_paths
from diffeoforge.mesh import sha256_file
from diffeoforge.reference_calibration import CalibrationCandidate


def screening_state(root, stage_id, events, candidates, *, verify=True):
    """Reconstruct a queue from the parent's hash-chained events."""
    relevant = [e for e in events if e.get("stage_id") == stage_id]
    starts = [e for e in relevant if e["event"] == "stage_screening_started"]
    if not starts:
        return {}
    start = starts[-1]
    by_id = {c.candidate_id: c for c in candidates}
    if not set(start["candidate_ids"]).issubset(by_id):
        raise ValueError("Screening queue differs from the current stage")
    for cid, digest in start["config_sha256"].items():
        if sha256_file(by_id[cid].config_path) != digest:
            raise ValueError("Screening source configuration changed")
    probes = {}
    decisions = {}
    retired = []
    for event in relevant:
        if event["sequence"] <= start["sequence"]:
            continue
        if event["event"] not in {
            "stage_screening_probe", "stage_screening_review", "stage_screening_failed",
            "stage_screening_retry",
        }:
            continue
        key = (event["candidate_id"], event["filename"])
        if key[0] not in start["candidate_ids"] or key[1] not in start["subjects"]:
            raise ValueError("Screening event is outside the declared queue")
        if event["event"] == "stage_screening_retry":
            failure = decisions.get(key)
            if (not failure or failure["event"] != "stage_screening_failed"
                    or failure["event_hash"] != event["failure_event_hash"]):
                raise ValueError("Screening retry is not bound to a technical failure")
            retired.append((probes.pop(key), decisions.pop(key)))
        elif event["event"] == "stage_screening_probe":
            probes[key] = event
        else:
            decisions[key] = event
    if verify:
        bindings = retired + [(event, decisions.get(key)) for key, event in probes.items()]
        for event, decision in bindings:
            child = study._safe_study_path(root, event["child"])
            if sha256_file(child / study.STUDY_MANIFEST) != event["manifest_sha256"]:
                raise ValueError("Screening study binding changed")
            for record in event["files"]:
                path = study._safe_study_path(root, record["copy"])
                if sha256_file(path) != record["sha256"]:
                    raise ValueError("Screening reference or initialization changed")
            if decision:
                snapshot = study.load_reference_calibration_study(child)
                candidate = snapshot.candidates[0]
                if decision["event"] == "stage_screening_failed":
                    if (candidate.status != "failed" or study._canonical_hash(
                        study._load_events(child)
                    ) != decision["events_sha256"]):
                        raise ValueError("Screening failure evidence changed")
                    continue
                if (
                    snapshot.visual_reviews.get(candidate.candidate_id) is not decision["approved"]
                    or study._candidate_review_binding(candidate) != decision["binding"]
                    or study._canonical_hash(study._read_review_journal(
                        study._search_extension_series(child)[0]
                    )) != decision["review_sha256"]
                ):
                    raise ValueError("Screening review changed or was withdrawn")
    rejected = []
    kept = []
    failed = []
    next_key = None
    for cid in start["candidate_ids"]:
        values = [decisions.get((cid, name)) for name in start["subjects"]]
        if any(v is not None and v["event"] == "stage_screening_failed" for v in values):
            failed.append(cid)
        elif any(v is not None and v["approved"] is False for v in values):
            rejected.append(cid)
        elif all(v is not None and v["approved"] is True for v in values):
            kept.append(cid)
        elif next_key is None:
            next_key = next((cid, name) for name, value in zip(
                start["subjects"], values, strict=True
            ) if value is None)
    current = probes.get(next_key)
    current_status = None
    if current:
        current_status = study.load_reference_calibration_study(
            study._safe_study_path(root, current["child"])
        ).candidates[0].status
    return dict(
        stage_id=stage_id, subjects=start["subjects"], candidate_ids=start["candidate_ids"],
        rejected=rejected, kept=kept, complete=next_key is None,
        next_candidate=next_key[0] if next_key else None,
        next_subject=next_key[1] if next_key else None,
        current_child=current["child"] if current else None,
        current_status=current_status,
        reviewed=len(rejected) + len(kept),
        technical_failures=failed,
        failed_screens=[dict(candidate_id=cid, filename=name, failure_event_hash=e["event_hash"])
                        for (cid, name), e in decisions.items()
                        if e["event"] == "stage_screening_failed"],
        failure_reasons={cid: next(e["reason"] for (option, _), e in decisions.items()
                                  if option == cid and e["event"] == "stage_screening_failed")
                        for cid in failed},
    )


def retry_failed_screens(directory):
    """Requeue only technical failures; preserve prior attempts and human decisions.

    Preparation only: no optimizer is launched by this action.
    """
    snapshot = study.load_reference_calibration_study(directory)
    state = snapshot.early_screening
    if not state or not state["technical_failures"]:
        raise ValueError("No technically failed screens to retry")
    if state["current_status"] == "running":
        raise ValueError("Wait until the current screen stops before retrying failures")
    for failure in state["failed_screens"]:
        study._append_event(snapshot.study_directory, "stage_screening_retry", dict(
            stage_id=state["stage_id"], **failure,
            meaning="Retry technical failure; original attempt and visual decisions preserved",
        ))
    return study.load_reference_calibration_study(snapshot.study_directory)


def start_screening(snapshot, subjects):
    stage = snapshot.current_stage
    if stage is None or stage.order not in (2, 3) or snapshot.plan.qc_recalibration_source:
        raise ValueError("Early screening is available only in ordinary stages 2 and 3")
    if snapshot.early_screening:
        raise ValueError("This stage already has a saved screening queue")
    names = tuple(subjects)
    cohort = {s.filename for s in snapshot.plan.selected_pilot_subjects}
    if not 1 <= len(names) <= 2 or len(set(names)) != len(names) or not set(names) <= cohort:
        raise ValueError("Choose one or two different pilot specimens")
    pending = tuple(c for c in snapshot.candidates if c.status != "completed")
    if not pending:
        raise ValueError("All options are already calculated; existing results are preserved")
    study._append_event(snapshot.study_directory, "stage_screening_started", dict(
        stage_id=stage.stage_id, subjects=names,
        candidate_ids=[c.candidate_id for c in pending],
        config_sha256={c.candidate_id: sha256_file(c.config_path) for c in pending},
        scope="fixed-reference singleton filter; separate joint QC required",
    ))
    return study.load_reference_calibration_study(snapshot.study_directory)


def _create_probe(snapshot, state):
    from diffeoforge.reference_pca import read_deformetrica_momenta
    from diffeoforge.reference_pca_deformations import _write_momenta
    from diffeoforge.reference_sequential_fit import _fingerprint

    root = snapshot.study_directory
    cid, name = state["next_candidate"], state["next_subject"]
    candidate = next(c for c in snapshot.candidates if c.candidate_id == cid)
    config = copy.deepcopy(load_config(candidate.config_path))
    inputs = validate_input_paths(config, candidate.config_path)
    parent = root / "early-screening" / state["stage_id"]
    parent.mkdir(parents=True, exist_ok=True)
    number = len(list(parent.glob("probe-*"))) + 1
    while (parent / f"probe-{number:03d}").exists():
        number += 1
    preparation = parent / f"probe-{number:03d}"
    preparation.mkdir()
    bound = []

    def copied(path, label):
        target = preparation / (label + path.suffix)
        study._copy_bound(path, target, sha256_file(path))
        bound.append(dict(copy=study._relative_path(root, target), sha256=sha256_file(target)))
        return str(target)

    config["input"].update(
        directory=str(root / study._verify_manifest(root)["inputs"]["subject_directory"]),
        template=copied(inputs.template, "template"), subject_pattern=name,
    )
    deformation = config["model"]["deformation"]
    if inputs.initial_control_points is not None:
        deformation["initial_control_points"] = copied(inputs.initial_control_points, "controls")
    if inputs.initial_momenta is not None:
        labels = deformation["initial_momenta_subjects"]
        values = read_deformetrica_momenta(inputs.initial_momenta, allow_singleton=True)
        if values.shape[0] != len(labels) or labels.count(name) != 1:
            raise ValueError("Screening momenta do not match the selected specimen")
        target = preparation / "momenta.txt"
        _write_momenta(target, values[labels.index(name):labels.index(name) + 1])
        bound.append(dict(copy=study._relative_path(root, target), sha256=sha256_file(target)))
        deformation.update(initial_momenta=str(target), initial_momenta_subjects=[name])
    config["optimization"].update(freeze_template=True, freeze_control_points=True)
    values = {
        "attachment_kernel_width": config["model"]["attachment"]["kernel_width"],
        "deformation_kernel_width": deformation["kernel_width"],
        "initial_control_point_spacing": deformation["initial_control_point_spacing"],
        "noise_std": config["model"]["noise_std"], "timepoints": deformation["timepoints"],
    }
    declarations = tuple(d for d in snapshot.plan.pilot_subject_declarations if d.filename == name)
    selected = tuple(s for s in snapshot.plan.selected_pilot_subjects if s.filename == name)
    probe_candidate = CalibrationCandidate(
        "screen-option", f"Screen {cid}: {name}", tuple(sorted(values.items())),
        "Fixed-reference single-specimen filter; not a joint atlas or joint approval",
    )
    plan = _fingerprint(replace(
        snapshot.plan, version="0.5" if declarations else "0.3",
        template_filename=inputs.template.name,
        template_sha256=sha256_file(Path(config["input"]["template"])),
        selected_pilot_subjects=selected, requested_pilot_subject_count=1,
        pilot_subject_declarations=declarations, required_subject_filenames=(name,),
        execution_scope="single_specimen_probe", search_extension_lineage=(),
        stages=(replace(snapshot.plan.stages[0], candidates=(probe_candidate,)),
                *snapshot.plan.stages[1:]),
    ))
    recommendation = config["project"]["parameter_provenance"]["recommendation"]
    recommendation["calibration_plan"] = plan.provenance
    source = preparation / "source.yaml"
    study._write_yaml(source, config, overwrite=False)
    child = study.create_reference_calibration_study(
        source, preparation / "study", plan_override=plan,
        pilot_max_iterations=int(config["optimization"]["max_iterations"]),
    )
    study._append_event(root, "stage_screening_probe", dict(
        stage_id=state["stage_id"], candidate_id=cid, filename=name,
        child=study._relative_path(root, child.study_directory), files=bound,
        manifest_sha256=sha256_file(child.study_directory / study.STUDY_MANIFEST),
    ))
    return child


def run_next_screen(runner, *, subjects=None, event_callback=None):
    """Calculate at most one singleton, then wait for a persisted human decision."""
    snapshot = study.load_reference_calibration_study(runner.study_directory)
    if subjects is not None:
        snapshot = start_screening(snapshot, subjects)
    state = snapshot.early_screening
    if not state:
        raise ValueError("Start an early screening queue first")
    if state["complete"] or runner._cancel_requested:
        return snapshot
    child = (
        study.load_reference_calibration_study(
            study._safe_study_path(snapshot.study_directory, state["current_child"])
        ) if state["current_child"] else _create_probe(snapshot, state)
    )
    if child.candidates[0].status != "completed":
        child_runner = study.ReferenceCalibrationStudyRunner(
            child.study_directory, controller_factory=runner._controller_factory
        )
        runner._active_controller = child_runner
        try:
            if not runner._cancel_requested:
                child_runner.run_current_stage(event_callback=(
                    lambda e: event_callback(dict(event="screen_progress", probe_event=e))
                ) if event_callback else None)
        finally:
            runner._active_controller = None
        terminal = study.load_reference_calibration_study(child.study_directory)
        if terminal.candidates[0].status == "failed":
            study._append_event(snapshot.study_directory, "stage_screening_failed", dict(
                stage_id=state["stage_id"], candidate_id=state["next_candidate"],
                filename=state["next_subject"], approved=False,
                events_sha256=study._canonical_hash(study._load_events(child.study_directory)),
                reason=terminal.candidates[0].error,
                meaning="Technical failure; no anatomical review was recorded",
            ))
    return study.load_reference_calibration_study(snapshot.study_directory)


def record_screen_review(directory, child_directory):
    root = Path(directory).resolve()
    # The viewer has just persisted a new child review. Do not validate an older
    # decision for this same child before binding its replacement to that review.
    parent = study.load_reference_calibration_study(root)
    state = parent.early_screening
    if not state or not state["current_child"]:
        raise ValueError("No current screen awaits a review")
    child = study._safe_study_path(root, state["current_child"])
    if child != Path(child_directory).resolve():
        raise ValueError("This screening viewer is stale")
    snapshot = study.load_reference_calibration_study(child)
    candidate = snapshot.candidates[0]
    approved = snapshot.visual_reviews.get(candidate.candidate_id)
    if not isinstance(approved, bool):
        raise ValueError("Record the specimen's visual decision first")
    study._append_event(root, "stage_screening_review", dict(
        stage_id=state["stage_id"], candidate_id=state["next_candidate"],
        filename=state["next_subject"], approved=approved,
        binding=study._candidate_review_binding(candidate),
        review_sha256=study._canonical_hash(study._read_review_journal(
            study._search_extension_series(child)[0]
        )),
    ))
    return study.load_reference_calibration_study(root)


def joint_candidate_ids(snapshot):
    state = snapshot.early_screening
    if not state:
        return None
    if not state["complete"]:
        raise ValueError("Review the early screens before running joint comparisons")
    return ({c.candidate_id for c in snapshot.candidates}
            - set(state["rejected"]) - set(state["technical_failures"]))
