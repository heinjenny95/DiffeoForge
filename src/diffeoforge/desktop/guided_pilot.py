"""Compact guided actions, separate method cards and visible recovery after rejection."""

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.guided_strategy import remaining_forms
from diffeoforge.guided_strategy import state as guidance_state
from diffeoforge.reference_guided_pilot import record


def render(window, prepared):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    snapshot = prepared.snapshot
    info = record(snapshot)
    guidance = getattr(prepared, "guidance", None) or guidance_state(snapshot)
    running = window._worker is not None or window._restoring_search
    controls = (
        window.find_fit_button,
        window.saved_searches_button,
        window.adaptive_fit_search,
        window.advanced_mode,
        window.afk_mode,
        window.outward_mode,
        window.collect_evidence_button,
        window.keep_previous_button,
        window.selection_combo,
        window.advance_button,
        window.compare_options_button,
        window.use_provisional_button,
        window.review_next_button,
        window.denser_model_button,
    )
    window._guided_hidden_visibility = {c: not c.isHidden() for c in controls}
    for control in controls:
        control.hide()
    window._visually_reviewed_candidates = set(snapshot.visual_reviews)
    window._visually_approved_candidates = {k for k, v in snapshot.visual_reviews.items() if v}
    title = QLabel(
        "Joint pilot check"
        if info["phase"] == "joint"
        else "Improve the fit"
        if info.get("goal") or (guidance["preferred"] and any(
            value is False for value in snapshot.visual_reviews.values()))
        else "Check another form"
        if info["phase"] == "validate"
        else "Choose a starting method: Current or Varifold"
    )
    title.setObjectName("sectionTitle")
    window.content_layout.addWidget(title)
    explanation = QLabel(
        f"One common configuration · {snapshot.plan.pilot_subject_count} pilot specimens."
        if info["phase"] == "joint"
        else f"{info['target']}\n{guidance['total']} selected pilot forms · "
        f"{guidance['checked']} checked with these settings · "
        f"{info['screen_trials_spent']} tests prepared so far."
    )
    explanation.setObjectName("pilotScope")
    explanation.setWordWrap(True)
    window.content_layout.addWidget(explanation)
    if info.get("goal"):
        from diffeoforge.pilot_recovery import DESCRIPTIONS

        reason = DESCRIPTIONS.get(info["goal"])
        if reason:
            description = QLabel(reason[0] + ". " + reason[1])
            description.setWordWrap(True)
            window.content_layout.addWidget(description)
    if info["phase"] == "screen":
        why = QLabel(
            "Current uses oriented surfaces; Varifold ignores normal direction. "
            "Choose a useful starting method even if details still need improvement. "
            "A method preference does not approve a poor fit."
        )
        why.setWordWrap(True)
        window.content_layout.addWidget(why)
    completed = [c for c in snapshot.candidates if c.status == "completed"]
    pending = [c for c in snapshot.candidates if c.status != "completed"]
    unresolved = [
        c for c in snapshot.candidates if c.status not in {"completed", "failed", "interrupted"}
    ]
    failed = [c for c in snapshot.candidates if c.status in {"failed", "interrupted"}]
    window.progress.setVisible(running or bool(completed))
    window.progress.setRange(0, len(snapshot.candidates))
    window.progress.setValue(len(completed))
    window.progress.setFormat(f"{len(completed)} of {len(snapshot.candidates)} trials completed")
    window.start_button.setText(
        f"Run joint check · {snapshot.plan.pilot_subject_count} specimens"
        if info["phase"] == "joint"
        else f"Compare Current / Varifold · {len(pending)} trials on 1 specimen"
        if len(snapshot.candidates) == 2
        else "Run prepared test · 1 trial on 1 specimen"
    )
    window.start_button.setVisible(bool(pending))
    window.start_button.setEnabled(not running)
    _set_action_emphasis(window.start_button, bool(pending) and not running)
    window.cancel_button.setVisible(running)
    window.cancel_button.setEnabled(running)
    inspected_feedback = any(
        value and value.get("current_inspected")
        for value in guidance.get("feedback", {}).values()
    )
    window.status.setText(
        "Computing the confirmed batch…"
        if running
        else "A trial failed. Inspect details, retry, or choose an approved alternative."
        if failed
        else "Feedback saved. Choose the next step below."
        if completed and inspected_feedback
        else "Inspect the fit, then choose the next step below."
        if completed
        else "Ready. Preparing this plan has started no fits."
    )

    def action(layout, label, kind, identifier, *, goal=None, available=True):
        button = QPushButton(label, window.content)
        enabled = not running and not unresolved and available
        button.setVisible(enabled)
        button.setEnabled(enabled)
        _set_action_emphasis(button, enabled)
        button.clicked.connect(
            lambda: window._start_pilot(adaptive=False, guided_action=(
                kind if kind == "finish_joint" else "adaptive_" + kind, identifier, goal))
        )
        layout.addWidget(button)
        return button

    # Candidate identity is captured by each card's callbacks, never a shared selector.
    for candidate in snapshot.candidates:
        card = QFrame(window.content)
        card.setObjectName("card")
        card.setProperty(
            "pilotMethod", snapshot.attachment_comparison["methods"][candidate.candidate_id]
        )
        card.setProperty("pilotCandidate", candidate.candidate_id)
        layout = QVBoxLayout(card)
        method_title = QLabel(candidate.label)
        method_title.setObjectName("sectionTitle")
        layout.addWidget(method_title)
        decision = snapshot.visual_reviews.get(candidate.candidate_id)
        feedback = guidance.get("feedback", {}).get(candidate.candidate_id)
        already_inspected = bool(feedback and feedback.get("current_inspected"))
        state = (
            "Suitable for this form"
            if decision is True
            else "Needs improvement"
            if decision is False
            else "Inspected · suitability not yet approved"
            if already_inspected
            else "Ready to inspect"
            if candidate.status == "completed"
            else "Computing / queued"
            if running
            else candidate.status.title()
        )
        runtime = (candidate.metrics or {}).get("runtime_seconds")
        if runtime is not None:
            state += f" · {runtime / 60:.1f} min"
        if (candidate.metrics or {}).get("converged") is False:
            state += " · iteration limit, provisional"
        label = QLabel(state)
        label.setWordWrap(True)
        layout.addWidget(label)
        initialization = snapshot.attachment_comparison.get("refinement", {})
        if initialization:
            starting = QLabel(
                "Starting from your saved fitted shape."
                if initialization.get("initialization") == "learned"
                else "This adjustment requires a fresh fit. "
                "Compare it with your saved starting fit."
            )
            starting.setWordWrap(True)
            layout.addWidget(starting)
        if candidate in failed:
            layout.addWidget(
                InfoDisclosure("Technical failure", candidate.error or "No usable result")
            )
        if candidate in completed and not running:
            inspect = QPushButton("Inspect " + candidate.label + " fit")
            inspect.setAccessibleName(inspect.text())
            inspect.setProperty("pilotCandidate", candidate.candidate_id)
            inspect.clicked.connect(lambda _checked=False, c=candidate: window._open_candidate(c))
            _set_action_emphasis(inspect, decision is None and not already_inspected)
            layout.addWidget(inspect)
            subjects = (
                (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
            )
            outcomes = [
                r["marked_regions"]["outcome"] for r in subjects.values() if r.get("marked_regions")
            ]
            if outcomes:
                message = (
                    "Marked-area or whole-shape distances worsened. Inspect the trade-off."
                    if "regression" in outcomes
                    else "Marked-area distances improved without a measured whole-shape "
                    "regression. Inspect to confirm."
                    if all(v == "improved" for v in outcomes)
                    else "Marked-area measurements are inconclusive. Visual review is still needed."
                )
                label = QLabel(message)
                label.setWordWrap(True)
                layout.addWidget(label)
            guards = [r["refinement_guard"] for r in subjects.values() if r.get("refinement_guard")]
            if any(g["outcome"] == "regression" for g in guards):
                warning = QLabel("This test worsened whole-shape agreement. Keep the earlier "
                                 "starting fit and inspect the difference before another change.")
                warning.setObjectName("statusWarning")
                warning.setWordWrap(True)
                layout.addWidget(warning)
            method = snapshot.attachment_comparison["methods"][candidate.candidate_id]
            valid = guidance.get("allowed", {}).get(candidate.candidate_id, False)
            if info["phase"] != "screen":
                from diffeoforge.desktop.guided_feedback import (
                    render_feedback,
                    render_starting_fits,
                )

                render_feedback(window, snapshot, candidate.candidate_id, layout, feedback)
                render_starting_fits(window, snapshot, candidate.candidate_id, layout, feedback)
            if decision is False and not valid:
                explanation = QLabel(
                    "This result is technically invalid. Check the failure, input meshes and "
                    "alignment before retrying; it cannot be a starting fit.")
                explanation.setWordWrap(True)
                layout.addWidget(explanation)
            if (decision is False and valid and not unresolved
                    and guidance["preferred"] != method and info["phase"] != "joint"):
                action(layout, "Use " + candidate.label + " as starting method → improve",
                       "prefer", candidate.candidate_id)
            has_start = bool(feedback and feedback["selected"])
            if ((decision is False or has_start) and (valid or has_start) and not unresolved
                    and (guidance["preferred"] == method or has_start or info["phase"] == "joint")):
                _recovery(window, snapshot, candidate, layout, guidance)
            if decision is True and info["phase"] != "joint":
                remaining = remaining_forms(snapshot, candidate.candidate_id, context=guidance)
                action(
                    layout,
                    "Use " + candidate.label + " → check remaining forms" if remaining
                    else "Use " + candidate.label + " → prepare joint check",
                    "confirm",
                    candidate.candidate_id,
                    available=not unresolved and valid,
                )
        window.content_layout.addWidget(card)
    if running or not completed:
        return
    approved = [c for c in completed if snapshot.visual_reviews.get(c.candidate_id) is True]
    if info["phase"] == "joint":
        action(
            window.content_layout,
            "Use reviewed joint fit → check time resolution",
            "finish_joint",
            approved[0].candidate_id if approved else None,
            available=len(approved) == 1,
        )
        return
    if len(snapshot.candidates) == 2:
        covered = {r["filename"] for r in info["approved"]} | {info["target"]}
        remaining = set(info["pilot_order"]) - covered
        action(
            window.content_layout,
            "No clear preference → compare another form (2 tests)",
            "tie",
            None,
            available=len(approved) == 2 and bool(remaining),
        )
        if len(approved) == 2 and not remaining:
            tie = QLabel(
                "Both methods passed the tested forms. Choose a starting method; "
                "recorded runtime can guide an efficiency choice."
            )
            tie.setWordWrap(True)
            window.content_layout.addWidget(tie)
    unsure = QLabel(
        "Mark a fit suitable when the shape features relevant to your study are represented. "
        "Missing shape or local detail means Needs improvement, even if the main outline fits. "
        "You can still choose that method as a starting point and improve it first. "
        "Close without recording if unsure."
    )
    unsure.setWordWrap(True)
    window.content_layout.addWidget(InfoDisclosure("Help with visual assessment", unsure))


def _recovery(window, snapshot, candidate, layout, guidance):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis
    from diffeoforge.guided_strategy import trial_proposal
    from diffeoforge.pilot_recovery import DESCRIPTIONS
    from diffeoforge.pilot_regions import SYMPTOMS

    identifier = candidate.candidate_id
    heading = QLabel("This configuration has not passed this form. What needs improvement?")
    heading.setWordWrap(True)
    heading.setObjectName("status")
    layout.addWidget(heading)
    symptoms = QComboBox()
    symptoms.setAccessibleName("What is wrong with " + candidate.label + "?")
    for key, label in SYMPTOMS.items():
        symptoms.addItem(label, key)
    saved_feedback = guidance.get("feedback", {}).get(identifier) or {}
    recorded = saved_feedback.get("feedback") or {}
    regions = recorded.get("problem_regions") or snapshot.problem_regions.get(identifier, {})
    first = next((r for rows in regions.values() for r in rows), None)
    symptoms.setCurrentIndex(symptoms.findData(
        recorded.get("symptom") or (first["symptom"] if first else "unsure")))
    layout.addWidget(symptoms)
    explanation = QLabel()
    explanation.setWordWrap(True)
    layout.addWidget(explanation)
    prepare = QPushButton()
    layout.addWidget(prepare)
    state = {}
    alternatives = QComboBox()
    alternatives.setAccessibleName("Alternative adjustment for " + candidate.label)
    alternatives.addItem("Use the suggested next step", None)
    for key, (title, _reason) in DESCRIPTIONS.items():
        alternatives.addItem(title, key)
    options = QFrame()
    options_layout = QVBoxLayout(options)
    options_layout.addWidget(alternatives)
    layout.addWidget(InfoDisclosure("Other adjustments", options))

    def update(*_):
        selected = alternatives.currentData()
        request = "goal:" + selected if selected else symptoms.currentData()
        proposed = trial_proposal(snapshot, identifier, request, context=guidance)
        state.clear()
        state.update(proposed)
        state["request"] = request
        explanation.setText(
            f"{proposed['reason']} "
            + ("Reuse a compatible saved single-form deformation on the same basis. "
               if proposed['goal'] in {'detail', 'weight', 'smooth'}
               else "This changes the deformation basis or method and needs a fresh start. ")
            + f"Next: 1 test on this form. If suitable, "
            f"{proposed['remaining_checks']} other form(s) need checking, then one joint fit. "
            "Earlier results stay saved. Whole-shape quality is also checked."
            + (" Several adjustments have been tried; inspect alignment, mesh quality and "
               "the starting template before investing in further tests."
               if proposed["hypothesis_count"] >= 3 else "")
            if proposed["available"] else
            "This unchanged combination has already been tested. Inspect saved alternatives "
            "or select another adjustment below; no repeat is prepared."
        )
        prepare.setText(proposed["title"] + " · prepare 1 trial on 1 specimen")
        prepare.setEnabled(proposed["available"])
        _set_action_emphasis(prepare, proposed["available"])
        data = guidance.get("feedback", {}).get(identifier)
        if data and data["needs_direction"]:
            prepare.setEnabled(False)
            _set_action_emphasis(prepare, False)
            explanation.setText(
                "Tell us whether the last change helped, or choose an earlier starting fit above. "
                "This prevents another change from building blindly on a worse attempt.")

    symptoms.currentIndexChanged.connect(update)
    alternatives.currentIndexChanged.connect(update)
    prepare.clicked.connect(
        lambda: window._start_pilot(
            adaptive=False, guided_action=("adaptive_recover", identifier, state["request"])
        )
    )
    update()
    if len(snapshot.candidates) == 1:
        other = QPushButton("Alternatively: check the other method here · prepare 1 trial")
        other_proposal = trial_proposal(snapshot, identifier, "other_method", context=guidance)
        data = guidance.get("feedback", {}).get(identifier)
        other.setEnabled(other_proposal["available"] and not (data and data["needs_direction"]))
        if not other_proposal["available"]:
            other.setText("Other method already tested here — compare saved alternatives")
        other.clicked.connect(
            lambda: window._start_pilot(
                adaptive=False, guided_action=("adaptive_recover", identifier, "other_method")
            )
        )
        layout.addWidget(other)
    checks = QLabel(
        "Check alignment and mesh quality if either method misses the same area. "
        "A marked area identifies the problem location, not its unique cause. "
        "Changed settings require renewed checks on the other pilot forms."
    )
    checks.setWordWrap(True)
    layout.addWidget(InfoDisclosure("Input and template checks", checks))
