"""Keep the visible anatomical comparison separate from the optimization seed."""

from pathlib import Path

from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided
from diffeoforge.guided_density import refinement_for
from diffeoforge.mesh import sha256_file


def common_review(snapshot, identifier, *, origin=None):
    """Identify both references, including a historical fit reviewed under a later protocol."""
    from diffeoforge.guided_feedback import reference, verify_reference
    from diffeoforge.pilot_common_diagnosis import accepted_reference
    from diffeoforge.pilot_form_progress import is_common_check, marker

    info = guided.record(snapshot)
    if not info or not info.get("target") or snapshot.plan.pilot_subject_count != 1:
        return None
    if origin is None and not is_common_check(info):
        return None
    origin = snapshot if origin is None else origin
    ledger = marker(origin)
    if not ledger or ledger["stage"] != "model":
        return None
    current = reference(snapshot, identifier)
    owner = guided.record(origin)
    if (owner["origin"] != info["origin"] or origin.study_directory != snapshot.study_directory
            and not any(entry["directory"] == current["directory"]
                        and entry["manifest_sha256"] == current["manifest_sha256"]
                        for entry in owner["history"])):
        raise ValueError("The common review must use a saved fit from this pilot's history")
    numerical_seed = starting_reference(snapshot, identifier)
    approved = accepted_reference(ledger, current["target"])
    if approved:
        previous = verify_reference(approved)
        if guided.record(previous)["origin"] != info["origin"]:
            raise ValueError("The approved individual comparison belongs to another pilot")
        if previous.visual_reviews.get(approved["candidate_id"]) is not True:
            approved = None
    return dict(current=current, numerical_seed=numerical_seed,
                approved_individual=approved,
                context_directory=str(origin.study_directory))


def starting_reference(snapshot, identifier):
    """Resolve the saved field used to start this trial, even on a branched history."""
    from diffeoforge.guided_feedback import reference
    from diffeoforge.pilot_multiscale_study import bound_snapshot

    refinement = refinement_for(snapshot.attachment_comparison, identifier)
    numerical_seed = (refinement.get("reference")
                      if refinement.get("initialization") in {"learned", "nested", "residual"}
                      else None)
    strategy = guided.record(snapshot).get("strategy") or {}
    capture = (strategy.get("common_multiscale") or {}).get("capture")
    if capture:
        previous = bound_snapshot(capture)
        numerical_seed = reference(previous, previous.candidates[0].candidate_id)
    return numerical_seed


def common_seed_source(ref):
    """Verify a numerical checkpoint, including one without a separate anatomical review."""
    from diffeoforge.guided_feedback import reference

    parent = study.load_reference_calibration_study(Path(ref["directory"]))
    if reference(parent, ref["candidate_id"], ref["target"]) != ref:
        raise ValueError("The common model's saved numerical starting fit changed")
    return parent


def inspected_start(ref):
    from diffeoforge.guided_feedback import inspected

    return ref if ref and inspected(common_seed_source(ref), ref["candidate_id"]) else None


def review_evidence(snapshot, identifier, decision):
    """Verify a new side-by-side rating before appending it to the existing journal."""
    if (decision.get("common_comparison_displayed") is not True
            or decision.get("comparison_displayed") is not True):
        raise ValueError("Wait for the selected comparison surface before rating this common fit")
    context_root = Path(decision.get("common_review_directory") or snapshot.study_directory)
    origin = (snapshot if context_root == snapshot.study_directory
              else study.load_reference_calibration_study(context_root))
    data = common_review(snapshot, identifier, origin=origin)
    if not data:
        raise ValueError("A common-model comparison requires a saved common protocol")
    expected = {name: data[name] for name in ("approved_individual", "numerical_seed")}
    if decision.get("common_review_references") != expected:
        raise ValueError("The common review references changed. Reopen the saved comparison.")
    comparison = decision["comparison"]
    owner = guided.record(origin)
    if (comparison["directory"] != str(origin.study_directory)
            and not any(entry["directory"] == comparison["directory"]
                        and entry["manifest_sha256"] == comparison["manifest_sha256"]
                        for entry in owner["history"])):
        raise ValueError("The displayed comparison must be a saved fit from this pilot's history")
    return dict(version=1, context_directory=data["context_directory"],
                context_manifest_sha256=sha256_file(origin.study_directory / study.STUDY_MANIFEST),
                **expected)


def seed_outcome(event):
    """Legacy decisions retain their recorded meaning. New relative ratings name their surface."""
    review = event.get("common_review")
    if review is None or event["comparison"] == review["numerical_seed"]:
        return event["outcome"]
    return None


def progress_feedback(events):
    """Find the latest judgement of progress for this field, starting fit and set of marks."""
    if not events:
        return None
    latest = events[-1]
    if "common_review" not in latest:
        return latest  # Existing journals retain their original interpretation.
    seed = latest["common_review"]["numerical_seed"]
    if not seed:
        return None
    for event in reversed(events):
        if (event.get("current") != latest.get("current")
                or event.get("common_review", {}).get("numerical_seed") != seed
                or event.get("problem_regions") != latest.get("problem_regions")):
            break
        if event["comparison"] == seed:
            return event
    return None


def current_progress_feedback(snapshot, parent, ref, events):
    """Only use a saved common judgement while its reviewed areas still match."""
    from diffeoforge.pilot_common_diagnosis import comparison_regions

    event = progress_feedback(events)
    if event and "common_review" in event:
        marks = comparison_regions(snapshot, parent, ref) or []
        if event.get("problem_regions", {}).get(ref["target"], []) != marks:
            return None
    return event
