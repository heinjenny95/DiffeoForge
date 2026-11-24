"""One explicit review destination, independent from selected repair/history fits."""


def choose(snapshot, guidance, info):
    reuse = next((row["common_reuse"] for row in guidance.get("next_forms", {}).values()
                  if row.get("available")
                  and (row.get("common_reuse") or {}).get("mode") in {"review", "feedback"}),
                 None)
    common = reuse or guidance.get("common_recovery")
    if common and (common.get("mode") in {"review", "feedback"} or common.get("review_reference")):
        number = common.get("test_number")
        attempt = f" · Test {number}" if number is not None else ""
        scope = ("control-point comparison" if common.get("comparison_kind") == "capacity"
                 else "common-model result")
        pending = common.get("mode") in {"review", "feedback"}
        if common.get("mode") == "feedback" and common.get("requested_comparison"):
            return dict(root=snapshot.study_directory, kind="common",
                reference=common.get("review_reference") or common["reference"], pending=True,
                label="Review progress from the starting fit" + attempt + " · " + common["target"],
                explanation=common["reason"])
        return dict(root=snapshot.study_directory, kind="common",
            reference=common.get("review_reference") or common["reference"],
            pending=pending, label=("Compare and give feedback · "
            if common.get("mode") == "feedback" else "Review " if pending else "Reopen ")
            + scope + attempt + " · " + common["target"],
            explanation="Review this saved common-model result. Earlier starting fits below "
                        "are separate repair or comparison options; this action starts no fitting.")
    completed = [c for c in snapshot.candidates if c.status == "completed"]
    candidate = next((c for c in completed if c.candidate_id not in snapshot.visual_reviews),
                     completed[0] if completed else None)
    if candidate is None:
        for stopped in snapshot.candidates:
            identifier = stopped.candidate_id
            failure = guidance.get("guard_failures", {}).get(identifier)
            if failure:
                parent = guidance.get("failed_parents", {}).get(identifier) or {}
                reference = parent.get("reference")
                areas = ", ".join(parent.get("area_labels", ()))
                return dict(root=snapshot.study_directory, kind="guard_stop",
                            candidate_id=identifier, reference=reference, pending=True,
                            label=("Inspect retained fit · " + parent["parent_label"]
                                   + (f" · marked areas {areas}" if areas else "")
                                   if reference else "Inspect stopped attempt"),
                            explanation=failure["message"] + (
                                " Inspect the saved starting fit before choosing another test."
                                if reference else " Open the attempt details to inspect the stop."))
        return None
    strategy = info.get("strategy") or {}
    optimization = strategy.get("optimization") or {}
    common_current = (not snapshot.attachment_comparison.get("regional_objective")
        and (info.get("goal") in {"shared_check", "form_model_check", "common_continue"}
             or any(strategy.get(k) for k in ("common_capacity_request",
                                              "common_candidate_step", "common_basis_step",
                                              "common_multiscale"))
             or optimization.get("common_model") is True))
    scope = ("joint" if info["phase"] == "joint" else "common-model"
             if common_current else "individual")
    from diffeoforge.pilot_form_progress import is_common_check

    direction = guidance.get("fit_direction") or {}
    repair = next((row for row in completed
                   if row.candidate_id == direction.get("identifier")), None)
    feedback_only = bool(
        scope == "individual" and not is_common_check(info)
        and direction.get("mode") in {"trial", "density", "return", "inputs"}
        and snapshot.plan.pilot_subject_count == 1
        and repair is not None and repair.candidate_id not in snapshot.visual_reviews
        and guidance.get("allowed", {}).get(repair.candidate_id)
        and (guidance.get("feedback", {}).get(repair.candidate_id) or {}).get(
            "current_inspected") is True
    )
    # Once both methods have decisions, reopen the method the researcher is
    # working on. A required review of the other method still takes priority.
    if feedback_only or (scope == "individual" and repair is not None
                         and all(c.candidate_id in snapshot.visual_reviews for c in completed)):
        candidate = repair
    pending = candidate.candidate_id not in snapshot.visual_reviews and not feedback_only
    name = info["target"] or f"{snapshot.plan.pilot_subject_count} forms"
    method = " · " + candidate.label if len(completed) > 1 else ""
    if (pending and scope == "individual" and any(
            proposal.get("available") and snapshot.visual_reviews.get(identifier) is True
            for identifier, proposal in guidance.get("next_forms", {}).items())):
        return dict(root=snapshot.study_directory, kind="current",
                    candidate_id=candidate.candidate_id, pending=False,
                    label=f"Inspect alternative fit{method} · {name}",
                    explanation="You already approved an individual fit for this specimen. "
                                "You can still inspect the other method.")
    return dict(root=snapshot.study_directory, kind="current", candidate_id=candidate.candidate_id,
        pending=pending, label=("Review " if pending else "Reopen inspected "
                               if feedback_only else "Reopen reviewed ") + scope
            + f" result · Test {info['screen_trials_spent']}" + method + " · " + name,
        explanation="Check this result, then choose Suitable fit or Needs improvement. "
                    "Earlier starting fits remain separate."
                    if pending else "Your feedback remains saved. Use the next-step action "
                    "to prepare the qualified repair. Suitable fit is a separate decision."
                    if feedback_only else "Your decision remains saved. Reopening this exact "
                    "result starts no fitting; use the next-step action to continue.")
