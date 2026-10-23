"""Inspected fit preferences and feedback, independent of anatomical approval."""

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.mesh import sha256_file

OUTCOMES = {"better": "Better", "same": "About the same", "worse": "Worse", "unsure": "Unsure"}


def severe_regression(snapshot, identifier):
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    subjects = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
    return any(r.get("refinement_guard", {}).get("severe") is True for r in subjects.values())


def reference(snapshot, identifier, target=None):
    candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
    metrics = candidate.metrics or {}
    if (candidate.status != "completed" or metrics.get("completed") is not True
            or type(metrics.get("invalid_face_count")) is not int
            or metrics["invalid_face_count"] != 0
            or metrics.get("subject_reconstruction_count") != snapshot.plan.pilot_subject_count):
        raise ValueError("Only a complete, technically valid fit can be a starting point")
    info = guided.record(snapshot)
    target = target or info["target"]
    if not target or target not in {s.filename for s in snapshot.plan.selected_pilot_subjects}:
        raise ValueError("Choose an individual original pilot form")
    return dict(directory=str(snapshot.study_directory), candidate_id=identifier,
        manifest_sha256=sha256_file(snapshot.study_directory / study.STUDY_MANIFEST),
        binding=study._candidate_review_binding(candidate), target=target,
        method=snapshot.attachment_comparison["methods"][identifier],
        values=next(c.values for c in snapshot.current_stage.candidates
                    if c.candidate_id == identifier))


def _local_events(snapshot, identifier=None):
    for event in study._load_events(snapshot.study_directory):
        if event["event"] == "guided_fit_feedback":
            ref = event["current"]
            if identifier is not None and ref["candidate_id"] != identifier:
                continue
            if ref != reference(snapshot, ref["candidate_id"], ref["target"]):
                raise ValueError("Saved feedback no longer matches this fit")
            if (event["outcome"] not in OUTCOMES or event["inspected_subjects"] != [ref["target"]]
                    or event["anatomical_approval_created"] is not False):
                raise ValueError("Invalid guided fit feedback")
            from diffeoforge.pilot_regions import SYMPTOMS

            if event.get("symptom", "unsure") not in SYMPTOMS:
                raise ValueError("Unknown saved fit problem")
            from diffeoforge.pilot_regions import validate

            manifest = study._verify_manifest(snapshot.study_directory)
            validate(event.get("problem_regions", {}), {
                r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]})
            yield event


def inspected(snapshot, identifier):
    return identifier in snapshot.visual_reviews or any(_local_events(snapshot, identifier))


def verify_reference(ref):
    root = Path(ref["directory"])
    if sha256_file(root / study.STUDY_MANIFEST) != ref["manifest_sha256"]:
        raise ValueError("Preferred starting-fit manifest changed")
    parent = study.load_reference_calibration_study(root)
    if (reference(parent, ref["candidate_id"], ref["target"]) != ref
            or not inspected(parent, ref["candidate_id"])):
        raise ValueError("Preferred starting fit or inspection binding changed")
    return parent


def _same_source(snapshot, ref):
    parent = verify_reference(ref)
    info, other = guided.record(snapshot), guided.record(parent)
    if (Path(info["origin"]).resolve() != Path(other["origin"]).resolve()
            or ref["target"] != info["target"]):
        raise ValueError("A starting fit must use the same cohort and original form")
    return parent


def selection(snapshot, identifier):
    """Latest explicit preference wins; no geometry metric invents a human preference."""
    for event in reversed(study._load_events(snapshot.study_directory)):
        if event["event"] == "guided_starting_fit_selected":
            _same_source(snapshot, event["reference"])
            return event["reference"]
        if (event["event"] == "guided_fit_feedback"
                and event["current"]["candidate_id"] == identifier):
            # Validate the current binding before allowing feedback to change a proposal.
            list(_local_events(snapshot, identifier))
            _same_source(snapshot, event["comparison"])
            return (event["current"] if event["outcome"] == "better"
                    and not severe_regression(snapshot, identifier) else event["comparison"])
    strategy = guided.record(snapshot).get("strategy") or {}
    anchor = strategy.get("anchor") or strategy.get("baseline")
    if anchor and anchor["target"] == guided.record(snapshot)["target"]:
        _same_source(snapshot, anchor)
        return anchor
    return None


def choices(snapshot, identifier):
    info = guided.record(snapshot)
    if not info or not info["target"]:
        return []
    result = []
    for row in [*reversed(info["history"]), None]:
        if (row and sha256_file(Path(row["directory"]) / study.STUDY_MANIFEST)
                != row["manifest_sha256"]):
            raise ValueError("Saved starting-fit history changed")
        other = study.load_reference_calibration_study(Path(row["directory"])) if row else snapshot
        other_info = guided.record(other)
        if not other_info or other_info["target"] != info["target"]:
            continue
        if Path(other_info["origin"]).resolve() != Path(info["origin"]).resolve():
            raise ValueError("Pilot history belongs to another cohort")
        for candidate in other.candidates:
            if not inspected(other, candidate.candidate_id):
                continue
            try:
                ref = reference(other, candidate.candidate_id)
            except ValueError:
                continue
            label = f"Test {other_info['screen_trials_spent']} · {candidate.label}"
            result.append(dict(reference=ref, label=label,
                trial_index=other_info["screen_trials_spent"],
                approved=other.visual_reviews.get(candidate.candidate_id) is True,
                current=other.study_directory == snapshot.study_directory
                        and identifier == candidate.candidate_id))
    return list({(r["reference"]["directory"], r["reference"]["candidate_id"]): r
                 for r in result}.values())


def presentation(snapshot, identifier):
    """Background-only verified data for the compact feedback/history controls."""
    info = guided.record(snapshot)
    if not info or not info["target"]:
        return None
    with study.calibration_verification_scope():
        rows = choices(snapshot, identifier)
        strategy = info.get("strategy") or {}
        comparison = strategy.get("baseline")
        if comparison:
            _same_source(snapshot, comparison)
        selected = selection(snapshot, identifier)
        current = None
        try:
            current = reference(snapshot, identifier)
        except ValueError:
            pass
        if selected and selected != current:
            comparison = selected
        feedback = list(_local_events(snapshot, identifier))
        explicitly_selected = any(e["event"] == "guided_starting_fit_selected"
                                  for e in study._load_events(snapshot.study_directory))
        return dict(choices=rows, comparison=comparison, selected=selected,
                    current_inspected=bool(current and inspected(snapshot, identifier)),
                    feedback=feedback[-1] if feedback else None,
                    problem_regions={info["target"]: regions(snapshot, identifier, info["target"])},
                    # An old chain without feedback starts with an explicit user choice.
                    needs_direction=bool(comparison and not feedback and not explicitly_selected))


def save_feedback(directory, identifier, decision):
    """Record an explicit inspected opinion; never record anatomical acceptance or run."""
    snapshot = study.load_reference_calibration_study(directory)
    current = reference(snapshot, identifier)
    outcome = decision["outcome"]
    comparison = decision["comparison"]
    _same_source(snapshot, comparison)
    if (outcome not in OUTCOMES or comparison == current
            or decision["inspected_subjects"] != [current["target"]]
            or not decision.get("display_scopes", {}).get(current["target"])):
        raise ValueError("Inspect the current original/reconstruction before saving feedback")
    note = decision.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("Feedback notes must contain at most 2000 characters")
    from diffeoforge.pilot_regions import SYMPTOMS, validate

    regions = decision.get("problem_regions", {})
    symptom = decision.get("symptom", "unsure")
    if symptom not in SYMPTOMS:
        raise ValueError("Choose what still needs improvement, or Unsure")
    manifest = study._verify_manifest(snapshot.study_directory)
    validate(regions, {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]})
    study._append_event(snapshot.study_directory, "guided_fit_feedback", dict(
        current=current, comparison=comparison, outcome=outcome, note=note,
        symptom=symptom,
        inspected_subjects=decision["inspected_subjects"],
        display_scopes=decision["display_scopes"],
        comparison_displayed=bool(decision.get("comparison_displayed")),
        problem_regions=regions,
        anatomical_approval_created=False, optimizer_started=False))
    return study.load_reference_calibration_study(directory)


def regions(snapshot, identifier, target):
    feedback = list(_local_events(snapshot, identifier))
    # A present empty mapping is an explicit Clear, not permission to resurrect a patch.
    if feedback and "problem_regions" in feedback[-1]:
        return feedback[-1]["problem_regions"].get(target, [])
    if identifier in snapshot.problem_regions:
        return snapshot.problem_regions[identifier].get(target, [])
    inherited = guided.record(snapshot).get("feedback") or {}
    return inherited.get("regions", []) if inherited.get("target") == target else []


def select(directory, identifier, ref):
    snapshot = study.load_reference_calibration_study(directory)
    _same_source(snapshot, ref)
    if ref not in [r["reference"] for r in choices(snapshot, identifier)]:
        raise ValueError("Choose a verified inspected fit from this form's saved history")
    study._append_event(snapshot.study_directory, "guided_starting_fit_selected", dict(
        reference=ref, anatomical_approval_created=False, optimizer_started=False))
    return study.load_reference_calibration_study(directory)
