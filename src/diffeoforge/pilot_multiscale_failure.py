"""Choose recovery for the recorded stage of a shared capture/detail test."""

from diffeoforge.pilot_multiscale_study import marker

EXECUTION_CANCELLED = (
    "Candidate execution was cancelled. Starting the stage "
    "again retains completed candidates and creates a new "
    "immutable attempt for this candidate."
)
_LEGACY_SOURCE_ERROR = "Original source geometry must be reviewed before this ordinary check"
_FAILURE_STATES = {"failed", "interrupted", "orphaned"}


def _accepted_reference(snapshot, declaration):
    from diffeoforge.guided_feedback import _same_source

    row = next((row for row in declaration["accepted_marker"]["reviews"]
                if row["filename"] == declaration["target"]), None)
    if row is None:
        return None
    ref = dict(row)
    ref["target"] = ref.pop("filename")
    try:
        parent = _same_source(snapshot, ref)
        if parent.visual_reviews.get(ref["candidate_id"]) is True:
            return ref
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, StopIteration):
        pass
    return None


def diagnose(snapshot, candidate, *, checks_available=None, capture_check_error=None,
             include_reference=True):
    """Use sealed stage evidence. A missing or unknown result cannot authorize another run."""
    declaration = marker(snapshot.attachment_comparison)
    if not declaration or (
        candidate.status not in _FAILURE_STATES and capture_check_error is None
    ):
        return None
    stage = declaration["stage"].title()
    detail = str(capture_check_error or candidate.error or "No terminal reason was recorded.")
    failure = getattr(candidate, "failure", None) or {}
    code = failure.get("code")
    if checks_available is None and candidate.status == "interrupted":
        from diffeoforge.reference_qualification_resume import verified_run

        try:
            checks_available = verified_run(snapshot, candidate) is not None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            return _report(
                snapshot, candidate, declaration, "inspect",
                f"{stage} checks cannot resume",
                "The saved native result could not be verified for these checks.",
                str(error), include_reference,
            )
    if checks_available:
        return _report(
            snapshot, candidate, declaration, "checks",
            f"{stage} fitting completed",
            "The saved native result passed verification. Resume its surface checks.",
            detail, include_reference,
        )
    if candidate.status == "interrupted" and (
        code == "template_preflight_cancelled" or detail == EXECUTION_CANCELLED
    ):
        return _report(
            snapshot, candidate, declaration, "retry",
            f"{stage} was cancelled",
            f"Run the same prepared {stage.lower()} stage in a new attempt.",
            detail, include_reference,
        )
    if code == "template_geometry" or detail == _LEGACY_SOURCE_ERROR:
        return _report(
            snapshot, candidate, declaration, "inspect_template",
            f"{stage} blocked by the shared template",
            detail if code == "template_geometry" else
            "The template has intersecting or nonpositive faces. Inspect the template "
            "before preparing another common-model test.",
            detail, include_reference,
        )
    if capture_check_error is not None:
        return _report(
            snapshot, candidate, declaration, "inspect",
            "Capture checks did not pass",
            "The saved capture did not qualify to initialize the detail stage.",
            detail, include_reference,
        )
    from diffeoforge.reference_guard_failure import for_candidate

    guard = for_candidate(candidate)
    if guard and guard["verified"]:
        return _report(
            snapshot, candidate, declaration, "inspect",
            f"{stage} stopped by a numerical check",
            guard["message"], guard["reason"], include_reference,
        )
    return _report(
        snapshot, candidate, declaration, "inspect",
        f"{stage} did not finish",
        "The recorded failure does not establish a safe retry.",
        detail, include_reference,
    )


def _report(snapshot, candidate, declaration, action, title, message, detail, include_reference):
    stage = declaration["stage"].title()
    reference = (
        _accepted_reference(snapshot, declaration)
        if action == "inspect" and include_reference else None
    )
    label = {
        "inspect": "Inspect approved individual fit",
        "inspect_template": "Inspect shared template",
        "retry": f"Retry saved {stage.lower()} stage",
        "checks": f"Resume saved {stage.lower()} checks",
    }[action]
    return dict(
        action=action, title=title, message=message, detail=detail, label=label,
        reference=reference, directory=snapshot.study_directory,
        candidate_id=candidate.candidate_id,
    )
