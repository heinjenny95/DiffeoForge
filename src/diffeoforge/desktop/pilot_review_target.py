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
        return None
    pending = candidate.candidate_id not in snapshot.visual_reviews
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
    name = info["target"] or f"{snapshot.plan.pilot_subject_count} forms"
    method = " · " + candidate.label if len(completed) > 1 else ""
    return dict(root=snapshot.study_directory, kind="current", candidate_id=candidate.candidate_id,
        pending=pending, label=("Review " if pending else "Reopen reviewed ") + scope
            + f" result · Test {info['screen_trials_spent']}" + method + " · " + name,
        explanation="Check this result, then choose Suitable fit or Needs improvement. "
                    "Earlier starting fits remain separate."
                    if pending else "Your decision remains saved. Reopening this exact result "
                    "starts no fitting; use the next-step action to continue.")
