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
    from diffeoforge.pilot_multiscale_study import bound_snapshot

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
    refinement = refinement_for(snapshot.attachment_comparison, identifier)
    numerical_seed = (refinement.get("reference")
                      if refinement.get("initialization") in {"learned", "nested", "residual"}
                      else None)
    capture = ((info.get("strategy") or {}).get("common_multiscale") or {}).get("capture")
    if capture:
        previous = bound_snapshot(capture)
        numerical_seed = reference(previous, previous.candidates[0].candidate_id)
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
