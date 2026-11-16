"""Bind pilot chat replies to the verified view and its real review actions."""

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QInputDialog

from diffeoforge.guided_density import controls_for
from diffeoforge.pilot_assistant import reply


def open_chat(window):
    from diffeoforge.desktop.pilot_assistant import show

    view = window._prepared_view
    if not view or window._view_loading or window._view_closed:
        return
    language = "de" if QLocale.system().language() == QLocale.Language.German else "en"
    context, callbacks = context_for_view(window, view, language=language)

    def invoke(action):
        if (window._prepared_view is not view
                or window.study_directory != view.snapshot.study_directory
                or window._view_loading or window._view_closed or window._review_saving
                or window._worker or window._restoring_search):
            window.status.setText("Pilot state changed. Reopen Pilot chat for the current actions.")
        elif action in callbacks:
            callbacks[action]()

    return show(window, context, reply=reply, invoke=invoke)


def context_for_view(window, view, *, language):
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
    if enabled(window.next_step_button) and not facts.get("next_label"):
        facts["next_label"] = window.next_step_button.text()
        # A chat action may open a view. Trial preparation stays in the regular pilot.
        mode = {"fit_direction_compare": "compare", "fit_direction_inputs": "inputs",
                "common_review": "review"}.get(footer[1]) if footer else None
        if mode:
            offer(mode, facts["next_label"], window.next_step_button.click)
            facts["next_action"] = mode
    if not facts.get("next_label") and enabled(window.start_button):
        facts["next_label"] = window.start_button.text()
    candidate_id = direction.get("identifier") or next(iter(marks), None)
    feedback = marks.get(candidate_id) or {}
    working = (direction.get("current") if direction.get("mode") == "return"
               else feedback.get("selected"))
    if not running and not review.get("pending"):
        history = []
        for row in feedback.get("choices", []):
            reference, label = row["reference"], row["label"]
            action = f"work:{len(history)}"
            offer(action, ("Ausgangsfit öffnen · " if language == "de" else "Open starting fit · ")
                  + label, lambda ref=reference: window._open_guided_working_fit(candidate_id, ref))
            history.append(action)
            facts["saved_tests"].setdefault(row["trial_index"], []).append((label, action))
            if reference == working:
                facts["working_label"], facts["working_action"] = label, action
                facts["working_quality_warning"] = direction.get("quality_warning")

        def choose_saved():
            title = "Gespeicherte Fits" if language == "de" else "Saved fits"
            prompt = "Ausgangsfit wählen" if language == "de" else "Choose a starting fit"
            options = [labels[key] for key in history]
            selected, ok = QInputDialog.getItem(window, title, prompt, options, editable=False)
            if ok:
                callbacks[history[options.index(selected)]]()

        if history:
            label = "Gespeicherte Fits" if language == "de" else "Saved fits"
            offer("history", label, choose_saved)
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
    return dict(assistant_actions=labels, assistant_language=language, facts=facts), callbacks
