"""Explicit cumulative pilot continuation through the verified native checkpoint route."""

from __future__ import annotations

import copy
from uuid import uuid4

from diffeoforge import reference_calibration_study as study
from diffeoforge.config import load_config, validate_schema
from diffeoforge.mesh import sha256_file

VERSION = "native-pilot-continuation-v1"


def latest(snapshot, identifier):
    """Follow verified completed descendants; a rejection never supplies a new seed."""
    current = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    for _ in snapshot.candidates:
        children = [c for c in snapshot.candidates if c.status == "completed"
                    and (c.metrics or {}).get("pilot_continuation", {}).get("source_candidate_id")
                    == current.candidate_id
                    and snapshot.visual_reviews.get(c.candidate_id) is not False
                    and c.metrics.get("invalid_face_count") == 0]
        if not children:
            return current
        current = children[-1]
    raise ValueError("Cyclic pilot continuation history")


def _configuration(source, evidence):
    config = copy.deepcopy(load_config(source.config_path))
    for key in ("directory", "template"):
        config["input"][key] = str((source.config_path.parent / config["input"][key]).resolve())
    for key in ("initial_control_points", "initial_momenta"):
        value = config["model"]["deformation"].get(key)
        if value:
            config["model"]["deformation"][key] = str(
                (source.config_path.parent / value).resolve()
            )
    config["optimization"] = copy.deepcopy(evidence.manifest["effective_config"]["optimization"])
    config["optimization"]["max_iterations"] += 300
    validate_schema(config)
    return config


def _checkpoint(source):
    from diffeoforge.reference_final_export_recovery import checkpoint_iteration
    from diffeoforge.runs import inspect_resume_source

    run = study.calibration_candidate_run_directory(source)
    evidence = inspect_resume_source(run, additional_iterations=300)
    planned = load_config(source.config_path)
    if (planned["model"]["deformation"]["timepoints"]
            != evidence.manifest["effective_config"]["model"]["deformation"]["timepoints"]):
        raise ValueError("Checkpoint uses another time grid. Keep the reviewed evaluated fit; "
                         "do not resume an optimizer on a different grid.")
    maximum = int(evidence.manifest["effective_config"]["optimization"]["max_iterations"])
    iteration = checkpoint_iteration(evidence.checkpoint_path)
    if iteration != maximum:
        raise ValueError("Latest pilot checkpoint does not contain the final capped iteration")
    return evidence, dict(
        version=VERSION, source_run=str(run),
        source_manifest_sha256=sha256_file(run / "manifest.json"),
        checkpoint_sha256=evidence.checkpoint_sha256,
        initial_iteration=iteration, additional_iterations=300, maximum_iterations=maximum + 300,
        history="Native parameters and iteration restored; objective baseline, gradient and "
        "line-search step sizes restart. Uninterrupted numerical trajectory is not claimed.",
    )


def prepare(snapshot, identifier, iterations=300):
    from diffeoforge.reference_adaptive_calibration import bind_learned_seed
    from diffeoforge.reference_pilot_qualification import CRITERIA, declarations

    if snapshot.current_stage is None or snapshot.current_stage.order != 4:
        raise ValueError("Saved joint pilot continuation belongs to Stage 4")
    if type(iterations) is not int or iterations != 300:
        raise ValueError("Native pilot continuation currently adds exactly 300 to the cap")
    root = snapshot.study_directory
    events = study._load_events(root)
    if any(not any(e["event"] in {"pilot_qualification_finished", "pilot_refinement_finished"}
                   and e.get("candidate_id") == d["candidate"]["candidate_id"] for e in events)
           for d in declarations(events)):
        raise ValueError("Resume the already declared check before preparing another continuation")
    source = latest(snapshot, identifier)
    evidence, checkpoint = _checkpoint(source)
    folder = root / "qualification" / uuid4().hex
    seed = bind_learned_seed(snapshot, source.candidate_id, folder)
    for bound in seed["files"].values():
        bound["copy"] = study._relative_path(root, folder / bound["copy"])
    config = _configuration(source, evidence)
    path = folder / "atlas.yaml"
    study._write_yaml(path, config, overwrite=False)
    completed = next(e for e in reversed(events) if e["event"] == "candidate_completed"
                     and e.get("stage_id") == snapshot.current_stage.stage_id
                     and e.get("candidate_id") == source.candidate_id)
    candidate_id = "continue-" + folder.name
    study._append_event(root, "pilot_qualification_declared", dict(
        version=VERSION, stage_id=snapshot.current_stage.stage_id,
        candidate=dict(candidate_id=candidate_id,
                       label=f"Continued fit · {checkpoint['maximum_iterations']} total iterations",
                       parameter_values=dict(timepoints=float(
                           config["model"]["deformation"]["timepoints"])),
                       rationale=checkpoint["history"]),
        config=study._relative_path(root, path), config_sha256=sha256_file(path),
        continuation_seed=seed, criteria=dict(CRITERIA), iterations=300,
        convergence_tolerance=config["optimization"]["convergence_tolerance"],
        source=dict(candidate_id=source.candidate_id, completed_event_hash=completed["event_hash"],
                    binding=study._candidate_review_binding(source)),
        checkpoint_continuation=checkpoint,
    ))
    return study.load_reference_calibration_study(root), candidate_id


def verify(root, event, events):
    from diffeoforge.reference_pilot_qualification import CRITERIA
    from diffeoforge.reference_stage_retention import _candidate

    earlier = tuple(e for e in events if e["sequence"] < event["sequence"])
    source, completed = _candidate(root, event["stage_id"], event["source"]["candidate_id"],
                                   events=earlier)
    if (event["source"]["completed_event_hash"] != completed["event_hash"]
            or event["source"]["binding"] != study._candidate_review_binding(source)):
        raise ValueError("Pilot continuation source evidence changed")
    evidence, expected = _checkpoint(source)
    path = study._safe_study_path(root, event["config"])
    config = _configuration(source, evidence)
    if (event["checkpoint_continuation"] != expected or event["criteria"] != CRITERIA
            or event["iterations"] != 300 or event["convergence_tolerance"]
            != config["optimization"]["convergence_tolerance"]
            or load_config(path) != config or sha256_file(path) != event["config_sha256"]
            or event["candidate"]["parameter_values"] != dict(timepoints=float(
                config["model"]["deformation"]["timepoints"]))
            or event["continuation_seed"]["source_manifest_sha256"]
            != event["source"]["binding"]["run_manifest_sha256"]):
        raise ValueError("Pilot continuation settings or checkpoint changed")
    for record in event["continuation_seed"]["files"].values():
        if sha256_file(study._safe_study_path(root, record["copy"])) != record["sha256"]:
            raise ValueError("Pilot continuation saved field changed")
    return source


def launch(root, event, attempt):
    from diffeoforge.desktop.reference_prelaunch import build_reference_resume_launch_request

    verify(root, event, study._load_events(root))
    return build_reference_resume_launch_request(
        event["checkpoint_continuation"]["source_run"],
        request_id="pilot-continue-" + uuid4().hex,
        run_id=f"{event['candidate']['candidate_id']}-attempt-{attempt:02d}",
        additional_iterations=300,
    )


def run(runner, identifier, iterations=300, event_callback=None):
    from diffeoforge.reference_pilot_qualification import run as qualify

    snapshot = study.load_reference_calibration_study(runner.study_directory)
    prepare(snapshot, identifier, iterations)
    return qualify(runner, event_callback=event_callback)
