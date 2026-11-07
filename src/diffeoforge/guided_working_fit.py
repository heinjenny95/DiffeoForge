"""Explicitly work from an inspected saved field without rewriting its study."""

from time import time_ns

from diffeoforge import guided_feedback as feedback
from diffeoforge import reference_calibration_study as study


def save(directory, identifier, decision):
    snapshot = study.load_reference_calibration_study(directory)
    ref = decision["reference"]
    feedback._same_source(snapshot, ref)
    if ref not in [r["reference"] for r in feedback.choices(snapshot, identifier)]:
        raise ValueError("Choose an inspected fit from this form's saved history")
    target = ref["target"]
    scope = decision.get("display_scopes", {}).get(target)
    if decision.get("inspected_subjects") != [target] or not isinstance(scope, str) or not scope:
        raise ValueError("Inspect this exact original and saved reconstruction before continuing")
    from diffeoforge.pilot_regions import validate

    rows = decision["problem_regions"]
    if set(rows) - {target}:
        raise ValueError("Only this inspected form's areas can be edited")
    manifest = study._verify_manifest(snapshot.study_directory)
    validate(rows, {r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]})
    study._append_event(snapshot.study_directory, "guided_starting_fit_selected", dict(
        reference=ref, editing_candidate_id=identifier, problem_regions=rows,
        inspected_subjects=[target], display_scopes={target: scope},
        region_edit=dict(version=2, recorded_at=time_ns(), cleared=[] if rows else [target]),
        anatomical_approval_created=False, optimizer_started=False))
    return study.load_reference_calibration_study(directory)


def edits(snapshot, identifier, target):
    """Validate new working-copy edits independently from fit-quality feedback."""
    for event in study._load_events(snapshot.study_directory):
        if (event["event"] != "guided_starting_fit_selected" or "region_edit" not in event
                or event.get("editing_candidate_id") != identifier):
            continue
        ref = event["reference"]
        feedback._same_source(snapshot, ref)
        if (ref["target"] != target or event["inspected_subjects"] != [target]
                or not event["display_scopes"].get(target)
                or event["anatomical_approval_created"] is not False
                or event["optimizer_started"] is not False):
            raise ValueError("Saved working-fit area identity changed")
        from diffeoforge.pilot_regions import validate

        manifest = study._verify_manifest(snapshot.study_directory)
        rows = validate(event["problem_regions"], {
            r["filename"]: r["sha256"] for r in manifest["inputs"]["subjects"]})
        cleared = event["region_edit"]["cleared"]
        if set(rows) - {target} or cleared != ([] if rows else [target]):
            raise ValueError("Invalid working-fit area edit")
        yield event["region_edit"]["recorded_at"], rows.get(target, []), target in cleared


def inputs(snapshot, identifier, context, *, verified=None):
    from diffeoforge.guided_search import inputs as search_inputs

    data = dict(verified) if verified is not None else search_inputs(
        snapshot, identifier, context, allow_continuation=False)
    data.pop("_regional_continuation_preview", None)
    data["references"] = dict(data["references"])
    ref = data["anchor"]
    if not ref:
        raise ValueError("Choose a saved starting fit first")
    parent = feedback.verify_reference(ref)
    candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
    # Keep the full search history/marks, but measure and plan from the selected
    # geometry. A newer failed result is neither the current seed nor its quality.
    context = dict(context, feedback={**context["feedback"], ref["candidate_id"]: {}})
    data.update(current=candidate, current_reference=ref, baseline=ref,
                severe=feedback.severe_regression(parent, ref["candidate_id"]), context=context)
    data["references"][ref["directory"]] = parent
    from diffeoforge.regional_continuation import prepare_preview

    data["_regional_continuation_preview"] = prepare_preview(parent, ref["candidate_id"], data)
    return parent, data


def propose(parent, request, data):
    from diffeoforge.guided_search import propose as search_proposal

    ref = data["anchor"]
    result = search_proposal(parent, ref["candidate_id"], request, data)
    if (result["available"] and (result.get("initialization_reference") != ref
            or result.get("initialization") not in {"learned", "nested", "residual"})):
        result = dict(result, available=False, blocked_reason=
            "This adjustment cannot retain the selected saved field. Choose a compatible "
            "adjustment or inspect another starting fit; no fresh restart is prepared.")
    return result


def trial(snapshot, identifier, request):
    from diffeoforge.guided_strategy import state

    parent, data = inputs(snapshot, identifier, state(snapshot))
    return propose(parent, request, data)
