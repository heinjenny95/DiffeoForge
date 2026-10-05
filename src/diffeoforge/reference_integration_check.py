"""Prospectively recorded engineering tolerances for the complete Stage 4 pilot."""

import copy
import math
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from diffeoforge import reference_calibration_study as study

DEFAULT_TOLERANCES = {
    "atlas_rms_relative": 0.005,
    "objective_relative": 0.01,
    "residual_relative": 0.01,
}


def verified_tolerances(manifest, stage, candidates, events):
    records = [e for e in events if e["event"] == "integration_tolerances_declared"
               and e.get("stage_id") == stage.stage_id]
    if not records:
        return {}
    if len(records) != 1 or stage.order != 4:
        raise ValueError("Invalid numerical tolerance declaration")
    record = records[0]
    values = record["tolerances"]
    if (set(values) != {*DEFAULT_TOLERANCES, "atlas_rms_absolute"}
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v <= 0 for v in values.values())
            or any(values[k] > 1 for k in DEFAULT_TOLERANCES)
            or record["candidate_ids"] != [c["candidate_id"] for c in
                                              manifest["plan"]["stages"][-1]["candidates"]]
            or record["subjects"] != [s["filename"] for s in manifest["inputs"]["subjects"]]
            or not math.isclose(values["atlas_rms_absolute"],
                                values["atlas_rms_relative"] * manifest["template_diagonal"])
            or any(e["event"] == "candidate_started" and e.get("stage_id") == stage.stage_id
                   and e["sequence"] < record["sequence"] for e in events)):
        raise ValueError("Numerical tolerances differ from their declared comparison")
    additions = [e for e in events if e["event"] == "integration_resolution_added"]
    if [c.candidate_id for c in candidates] != record["candidate_ids"] + [
        e["candidate"]["candidate_id"] for e in additions
    ]:
        raise ValueError("Numerical candidate queue differs from its declarations")
    for addition in additions:
        if (addition["tolerances"] != values
                or addition["tolerance_event_hash"] != record["event_hash"]
                or addition["sequence"] <= record["sequence"]
                or any(e["event"] == "candidate_started"
                       and e.get("candidate_id") == addition["candidate"]["candidate_id"]
                       and e["sequence"] < addition["sequence"] for e in events)):
            raise ValueError("Added resolution was not declared before execution")
    return dict(values)


def declare_tolerances(snapshot, values=None):
    if snapshot.current_stage is None or snapshot.current_stage.order != 4:
        raise ValueError("Numerical tolerances belong to Stage 4")
    if snapshot.integration_tolerances:
        if values is not None and dict(values) != {
            k: snapshot.integration_tolerances[k] for k in DEFAULT_TOLERANCES
        }:
            raise ValueError("Numerical tolerances are already bound to this comparison")
        return snapshot
    if any(c.attempts for c in snapshot.candidates):
        if values is not None:
            raise ValueError("Declare tolerances before running any timepoint option")
        return snapshot  # Preserve the meaning of legacy completed/partial comparisons.
    values = dict(DEFAULT_TOLERANCES if values is None else values)
    if set(values) != set(DEFAULT_TOLERANCES) or any(
        isinstance(v, bool) or not isinstance(v, (int, float))
        or not math.isfinite(v) or not 0 < v <= 1 for v in values.values()
    ):
        raise ValueError("Numerical tolerances must be finite positive fractions up to one")
    manifest = study._verify_manifest(snapshot.study_directory)
    values["atlas_rms_absolute"] = values["atlas_rms_relative"] * manifest["template_diagonal"]
    study._append_event(snapshot.study_directory, "integration_tolerances_declared", dict(
        stage_id=snapshot.current_stage.stage_id, tolerances=values,
        candidate_ids=[c.candidate_id for c in snapshot.candidates],
        subjects=[s.filename for s in snapshot.plan.selected_pilot_subjects],
        basis="RMS / bound template diagonal; relative objective; worst subject residual",
        meaning="Engineering discretization criteria, not anatomical or biological approval",
    ))
    return study.load_reference_calibration_study(snapshot.study_directory)


def overlay_plan(plan, events):
    """Append declared finer resolutions without rewriting the original plan."""
    from diffeoforge.reference_calibration import CalibrationCandidate, _canonical_hash

    changed = False
    for event in events:
        if event["event"] != "integration_resolution_added":
            continue
        stage = plan.stages[-1]
        declaration = event["candidate"]
        next_count = int(stage.candidates[-1].values["timepoints"]) + 10
        if (event.get("version") != "integration-extension-v1"
                or event.get("stage_id") != stage.stage_id or stage.order != 4
                or declaration["candidate_id"] != f"timepoints-{len(stage.candidates) + 1:02d}"
                or declaration["parameter_values"] != {"timepoints": float(next_count)}):
            raise ValueError("Invalid finer-resolution declaration")
        candidate = CalibrationCandidate(
            declaration["candidate_id"], declaration["label"],
            tuple(sorted(declaration["parameter_values"].items())), declaration["rationale"],
        )
        stage = replace(stage, candidates=(*stage.candidates, candidate))
        plan = replace(plan, stages=(*plan.stages[:-1], stage))
        changed = True
    if changed:
        payload = plan.provenance
        for key in ("fingerprint", "status", "pilot_subject_count"):
            payload.pop(key)
        plan = replace(plan, fingerprint=_canonical_hash(payload))
    return plan


def verify_extension(root, event, events):
    from diffeoforge.config import load_config
    from diffeoforge.mesh import sha256_file

    source = event["source"]
    earlier = tuple(e for e in events if e["sequence"] < event["sequence"])
    completed = next((e for e in reversed(earlier)
                      if e["event"] == "candidate_completed"
                      and e.get("stage_id") == "timepoints"
                      and e.get("candidate_id") == source["candidate_id"]), None)
    if completed is None:
        raise ValueError("Finer-resolution source is not completed")
    prepared = study._prepared_candidates(root, earlier, "timepoints")[source["candidate_id"]]
    candidate = study.CalibrationStudyCandidateState(
        source["candidate_id"], "Finer-resolution source", "completed",
        study._safe_study_path(root, prepared["config"]),
        study._safe_study_path(root, completed["run_directory"]),
        completed["metrics"], None, int(completed["attempt"]),
    )
    if (completed["event_hash"] != source["completed_event_hash"]
            or study._candidate_review_binding(candidate) != source["binding"]
            or completed["sequence"] >= event["sequence"]):
        raise ValueError("Finer-resolution source evidence changed")
    seed = event["continuation_seed"]
    if (seed["candidate_id"] != source["candidate_id"]
            or seed["source_manifest_sha256"] != sha256_file(
                study.calibration_candidate_run_directory(candidate) / "manifest.json")):
        raise ValueError("Finer-resolution initialization differs from its source")
    for bound in seed["files"].values():
        path = study._safe_study_path(root, bound["copy"])
        if not path.is_file() or sha256_file(path) != bound["sha256"]:
            raise ValueError("Finer-resolution initialization changed")
    config = load_config(study._safe_study_path(root, event["config"]))
    expected = _configuration(
        root, candidate.config_path, study._safe_study_path(root, event["config"]).parent,
        seed, int(event["candidate"]["parameter_values"]["timepoints"]),
    )
    manifest = study._verify_manifest(root)
    names = [s["filename"] for s in sorted(
        manifest["inputs"]["subjects"], key=lambda s: Path(s["filename"])
    )]
    metrics = candidate.metrics
    if (config != expected or seed["subject_labels"] != names
            or not metrics.get("converged") or metrics.get("invalid_face_count") != 0
            or metrics.get("fit_scope") not in (None, "full_targets")
            or metrics.get("subject_reconstruction_count") != len(names)):
        raise ValueError("Finer resolution changed a locked configuration or valid full cohort")
    decisions = [e for e in events if e["event"] == "stage_selected"
                 and e.get("stage_id") == "timepoints"
                 and e["sequence"] < event["sequence"]]
    if decisions:
        raise ValueError("Cannot extend an already selected integration stage")


def _configuration(root, source_path, folder, seed, count):
    from diffeoforge.config import load_config, validate_schema
    from diffeoforge.reference_adaptive_calibration import apply_seed

    config = copy.deepcopy(load_config(source_path))
    config["input"]["directory"] = str(
        (source_path.parent / config["input"]["directory"]).resolve())
    config["model"]["deformation"]["timepoints"] = count
    apply_seed(config, root=root, candidate_directory=folder, seed=seed, initialization="warm")
    config["optimization"] = copy.deepcopy(seed["optimization"])
    validate_schema(config)
    return config


def next_resolution(snapshot):
    if snapshot.current_stage is None or snapshot.current_stage.order != 4:
        return None
    if not snapshot.integration_tolerances:
        return None  # Legacy comparisons retain their original meaning.
    if not all(c.status == "completed" for c in snapshot.candidates):
        return None
    last = snapshot.candidates[-1]
    metrics = last.metrics or {}
    if (not metrics.get("converged") or metrics.get("invalid_face_count") != 0
            or metrics.get("fit_scope") not in (None, "full_targets")
            or metrics.get("subject_reconstruction_count") != snapshot.plan.pilot_subject_count
            or snapshot.visual_reviews.get(last.candidate_id) is False):
        return None
    return int(snapshot.current_stage.candidates[-1].values["timepoints"]) + 10


def add_finer_resolution(directory):
    """Prepare one complete-cohort comparison; never execute or approve a fit."""
    from diffeoforge.mesh import sha256_file
    from diffeoforge.reference_adaptive_calibration import bind_learned_seed
    from diffeoforge.reference_calibration import CalibrationCandidate

    with study._REVIEW_LOCK:
        snapshot = study.load_reference_calibration_study(directory)
        count = next_resolution(snapshot)
        if count is None:
            raise ValueError("Finish the complete Stage 4 comparison first; its finest fit "
                             "must be converged, valid and not visually rejected")
        root = snapshot.study_directory
        stage = snapshot.current_stage
        previous = snapshot.candidates[-1]
        candidate = CalibrationCandidate(
            f"timepoints-{len(stage.candidates) + 1:02d}", f"{count} time points",
            (("timepoints", float(count)),),
            "Additional next-finer full-cohort reference; existing tolerances remain fixed.",
        )
        folder = root / "integration-extensions" / (candidate.candidate_id + "-" + uuid4().hex)
        seed = bind_learned_seed(snapshot, previous.candidate_id, folder)
        for bound in seed["files"].values():
            bound["copy"] = study._relative_path(root, folder / bound["copy"])
        config = _configuration(root, previous.config_path, folder, seed, count)
        config_path = folder / "atlas.yaml"
        study._write_yaml(config_path, config, overwrite=False)
        events = study._load_events(root)
        completed = next(e for e in reversed(events) if e["event"] == "candidate_completed"
                         and e.get("stage_id") == stage.stage_id
                         and e.get("candidate_id") == previous.candidate_id)
        tolerance = next(e for e in events if e["event"] == "integration_tolerances_declared")
        study._append_event(root, "integration_resolution_added", dict(
            version="integration-extension-v1", stage_id=stage.stage_id,
            candidate=candidate.as_manifest(), config=study._relative_path(root, config_path),
            config_sha256=sha256_file(config_path), parameter_values=candidate.values,
            continuation_seed=seed, tolerances=dict(snapshot.integration_tolerances),
            tolerance_event_hash=tolerance["event_hash"],
            source=dict(candidate_id=previous.candidate_id,
                        completed_event_hash=completed["event_hash"],
                        binding=study._candidate_review_binding(previous)),
        ))
        return study.load_reference_calibration_study(root)
