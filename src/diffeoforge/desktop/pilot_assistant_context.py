"""Bind pilot chat replies to the verified view and its real review actions."""

from PySide6.QtWidgets import QInputDialog

from diffeoforge.guided_density import controls_for
from diffeoforge.pilot_assistant import reply


def open_chat(window):
    from diffeoforge.desktop.pilot_assistant import show

    view = window._prepared_view
    if not view or window._view_loading or window._view_closed:
        return
    context, callbacks = context_for_view(window, view)

    def invoke(action):
        if (window._prepared_view is not view
                or window.study_directory != view.snapshot.study_directory
                or window._view_loading or window._view_closed or window._review_saving
                or window._worker or window._restoring_search):
            window.status.setText("Pilot state changed. Reopen Pilot chat for the current actions.")
        elif action in callbacks:
            callbacks[action]()

    return show(window, context, reply=reply, invoke=invoke)


def context_for_view(window, view):
    snapshot, guidance = view.snapshot, view.guidance
    running = window._worker is not None or window._restoring_search
    record = snapshot.attachment_comparison
    direction = guidance.get("fit_direction") or {}
    review = window._guided_review_target or {}
    pair = record.get("early_density_comparison")
    marks = guidance.get("feedback", {})
    facts = dict(running=running, saved_tests={}, coverage=(guidance["checked"], guidance["total"]))
    labels, callbacks = {}, {}

    def offer(action, label, callback):
        labels[action], callbacks[action] = label, callback

    def enabled(button):
        return not button.isHidden() and button.isEnabled() and not running

    if enabled(window.review_next_button):
        offer("review", window.review_next_button.text(), window.review_next_button.click)
        if review.get("pending"):
            facts["next_label"], facts["next_action"] = labels["review"], "review"
    footer = window._guided_footer_action
    footer_action = footer[1] if footer else None
    if enabled(window.next_step_button) and not facts.get("next_label"):
        facts["next_label"] = window.next_step_button.text()
        # A chat action may open a view. Trial preparation stays in the regular pilot.
        mode = {"fit_direction_compare": "compare", "fit_direction_inputs": "inputs",
                "inspect_failed_template": "inputs", "common_retained": "retained",
                "common_review": "review"}.get(footer_action)
        if mode:
            offer(mode, facts["next_label"], window.next_step_button.click)
            facts["next_action"] = mode
    if not facts.get("next_label") and enabled(window.start_button):
        facts["next_label"] = window.start_button.text()
    failure = next(iter(guidance.get("common_stage_failures", {}).values()), None)
    common = guidance.get("common_recovery") or {}
    inspecting_common = (footer_action == "fit_direction_inputs"
                         and common.get("mode") == "inspect_alignment")
    if failure and not running:
        facts["next_reason"] = failure["message"]
    elif common.get("reason") and (inspecting_common
            or footer_action in {"adaptive_common_continue", "common_retained"}):
        facts["next_reason"] = common["reason"]
        facts["expected_result"] = common.get("expected")
    elif direction and footer_action in {
        "fit_direction_compare", "fit_direction_inputs", "fit_direction_working",
        "adaptive_recover", "adaptive_recover_start", "adaptive_density_comparison",
    }:
        facts["next_reason"] = direction["reason"]
    accepted = ((common.get("diagnosis") or {}).get("accepted")
                or common.get("accepted_reference"))
    if accepted and not running:
        offer("accepted", "Inspect accepted individual fit",
              lambda: window._open_guided_saved_fit(accepted))
    candidate_id = direction.get("identifier") or next(iter(marks), None)
    feedback = marks.get(candidate_id) or {}
    working = (direction.get("current") if direction.get("mode") == "return"
               else feedback.get("selected"))
    if not running and not review.get("pending"):
        history = []
        for row in feedback.get("choices", []):
            reference, label = row["reference"], row["label"]
            action = f"work:{len(history)}"
            restore_partial = reference == working and direction.get("partial")
            options = {"restore_partial": True} if restore_partial else {}
            offer(action, "Open starting fit · " + label,
                  lambda ref=reference, opts=options: window._open_guided_working_fit(
                      candidate_id, ref, **opts))
            history.append(action)
            facts["saved_tests"].setdefault(row["trial_index"], []).append((label, action))
            if reference == working:
                facts["working_label"], facts["working_action"] = label, action
                facts["working_quality_warning"] = direction.get("quality_warning")

        def choose_saved():
            options = [labels[key] for key in history]
            selected, ok = QInputDialog.getItem(
                window, "Saved fits", "Choose a starting fit", options, editable=False)
            if ok:
                callbacks[history[options.index(selected)]]()

        if history:
            offer("history", "Saved fits", choose_saved)
        if working and "inputs" not in labels:
            from diffeoforge.desktop.guided_diagnosis import inspect_inputs

            offer("inputs", "Inspect template and alignment",
                  lambda: inspect_inputs(window, working))
        if direction.get("mode") == "return" and facts.get("working_action"):
            facts["next_action"] = facts["working_action"]
    if pair:
        ids = pair["reference_candidate_id"], pair["denser_candidate_id"]
        facts["density_counts"] = tuple(controls_for(record, key)["count"] for key in ids)
        facts["density_rejected"] = all(snapshot.visual_reviews.get(key) is False for key in ids)
        facts["density_worse"] = facts["density_rejected"] and all(
            ((marks.get(key) or {}).get("feedback") or {}).get("outcome") == "worse" for key in ids)
    review_id = review.get("candidate_id")
    candidate = next((c for c in snapshot.candidates if c.candidate_id == review_id), None)
    if candidate is not None:
        from diffeoforge.guided_progress import iteration_limited

        facts["iteration_limit"] = iteration_limited(candidate)
    return dict(assistant_actions=labels, facts=facts), callbacks
