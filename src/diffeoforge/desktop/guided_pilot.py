"""Compact guided actions, separate method cards and visible recovery after rejection."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.guided_strategy import remaining_forms
from diffeoforge.reference_guided_pilot import record


def render(window, prepared):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    snapshot = prepared.snapshot
    # Let the scroll area grow its content rather than compressing recovery cards.
    window.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    window.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    info = record(snapshot)
    guidance = prepared.guidance
    guard_failures = guidance.get("guard_failures", {})
    running = window._worker is not None or window._restoring_search
    regional_accepted = bool(
        snapshot.attachment_comparison.get("regional_objective")
        and any(snapshot.visual_reviews.get(c.candidate_id) is True
                for c in snapshot.candidates if c.status == "completed")
    )
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
        else "Suitable fit saved"
        if regional_accepted
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
    if info["phase"] == "joint":
        flags = snapshot.attachment_comparison.get("confirmation_freeze_settings", {})
        moving = [name for key, name in (("freeze_template", "template"),
                  ("freeze_control_points", "control points")) if flags.get(key) is False]
        conditions = QLabel(
            "The individual checks kept template and control points fixed. "
            + ("This joint test also estimates the shared " + " and ".join(moving) + ". "
               if moving else "This joint test retains those fixed settings. ")
            + ("It starts from all accepted individual deformation fields on the same "
               "original basis; optimizer history starts anew. "
               if snapshot.attachment_comparison.get("joint_initialization") else
               "It starts new deformation fields; the accepted individual fields are "
               "not its initialization. ")
            + "The shared model can still change individual fits. "
            "Review every form; individual suitability does not "
            "approve this joint result.")
        conditions.setWordWrap(True)
        conditions.setObjectName("jointFitConditions")
        window.content_layout.addWidget(conditions)
    if info.get("goal") and not regional_accepted and not guard_failures:
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
    retry_blocked = any(c.candidate_id in guard_failures for c in pending)
    window.progress.setVisible(running or bool(completed))
    window.progress.setRange(0, len(snapshot.candidates))
    window.progress.setValue(len(completed))
    window.progress.setFormat(f"{len(completed)} of {len(snapshot.candidates)} trials completed")
    window.start_button.setText(
        "Review numerical failure · this test cannot be rerun"
        if retry_blocked
        else f"Run joint check · {snapshot.plan.pilot_subject_count} specimens"
        if info["phase"] == "joint"
        else f"Compare Current / Varifold · {len(pending)} trials on 1 specimen"
        if len(snapshot.candidates) == 2
        else "Run prepared test · 1 trial on 1 specimen"
    )
    window.start_button.setVisible(bool(pending))
    window.start_button.setEnabled(not running and not retry_blocked)
    window.start_button.setToolTip(
        "Inspect the retained fit and numerical failure. The same failed test cannot be rerun."
        if retry_blocked else ""
    )
    _set_action_emphasis(window.start_button, bool(pending) and not running and not retry_blocked)
    window.cancel_button.setVisible(running)
    window.cancel_button.setEnabled(running)
    inspected_feedback = any(
        value and value.get("current_inspected")
        for value in guidance.get("feedback", {}).values()
    )
    window.status.setText(
        "Computing the confirmed batch…"
        if running
        else "Numerical check stopped a trial. Inspect the retained fit and failure details."
        if retry_blocked
        else "A trial failed. Inspect details, retry, or choose an approved alternative."
        if failed
        else "Fit saved as suitable. Inspect or close; further refinement is optional."
        if regional_accepted
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
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        card.setObjectName("card")
        card.setProperty(
            "pilotMethod", snapshot.attachment_comparison["methods"][candidate.candidate_id]
        )
        card.setProperty("pilotCandidate", candidate.candidate_id)
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        method_title = QLabel(candidate.label)
        method_title.setObjectName("sectionTitle")
        layout.addWidget(method_title)
        decision = snapshot.visual_reviews.get(candidate.candidate_id)
        feedback = guidance.get("feedback", {}).get(candidate.candidate_id)
        already_inspected = bool(feedback and feedback.get("current_inspected"))
        state = (
            candidate.status.title()
            if candidate.status in {"failed", "interrupted"}
            else "Suitable for this form"
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
        total = (candidate.metrics or {}).get("pipeline_wall_seconds")
        if total is not None:
            state += f" · {total / 60:.1f} min total"
            if runtime is not None:
                state += f" ({runtime / 60:.1f} min including review waits)"
        elif runtime is not None:
            state += f" · {runtime / 60:.1f} min"
        from diffeoforge.guided_progress import iteration_limited

        if iteration_limited(candidate):
            state += " · iteration limit, provisional"
        elif (candidate.metrics or {}).get("optimizer_stop_signal") == "pilot_review_request":
            state += " · ended at intermediate review, not converged"
        label = QLabel(state)
        label.setWordWrap(True)
        layout.addWidget(label)
        subjects = (candidate.metrics or {}).get("attachment_comparison", {}).get("subjects", {})
        quality = next((r["regional_quality"] for r in subjects.values()
                        if r.get("regional_quality")), None)
        if quality:
            failures = [label for key, label in [("transition_preserved", "transition fit"),
                         ("outside_preserved", "preservation outside the area"),
                         ("shape_preserved", "preservation of marked part shape")]
                        if not quality[key]]
            if not quality.get("no_new_intersection_flags", True):
                failures.append("new surface intersection flags")
            if not quality.get("temporal_grid_stable", True):
                failures.append("time-grid stability")
            if not quality.get("spatial_resolution_sufficient", True):
                failures.append("original-source spatial resolution limit")
            note = QLabel(
                "Your suitable-fit decision is saved. Surface checks still report: "
                + ", ".join(failures)
                + ". Atlas checks remain separate."
                if decision is True and failures else
                "This attempt fails: " + ", ".join(failures)
                + ". It will not replace your retained starting fit."
                if failures else
                          "Local, transition and preservation checks passed; inspect anatomy. "
                          "This regional objective still needs a shared cohort protocol.")
            note.setWordWrap(True)
            layout.addWidget(note)
        initialization = snapshot.attachment_comparison.get("refinement", {})
        if initialization:
            starting = QLabel(
                "Starting from your saved fitted shape; optimizer history starts anew."
                if initialization.get("initialization") == "learned"
                else "Starting from the saved deformation with additional zero-momentum "
                "control points; optimizer history starts anew."
                if initialization.get("initialization") == "nested"
                else "Retaining your saved deformation as a fixed prefix and fitting a "
                "local residual. The complete field chain is evaluated from the original source."
                if initialization.get("initialization") == "residual"
                else "This adjustment requires a fresh fit. "
                "Compare it with your saved starting fit."
            )
            starting.setWordWrap(True)
            layout.addWidget(starting)
        if candidate in failed:
            failure = guard_failures.get(candidate.candidate_id)
            if failure:
                note = QLabel(failure["message"])
                note.setWordWrap(True)
                note.setObjectName("statusWarning")
                layout.addWidget(note)
            layout.addWidget(
                InfoDisclosure("Technical failure", failure["reason"] if failure
                               else candidate.error or "No usable result")
            )
            if not running and candidate.status == "failed":
                from diffeoforge.desktop.guided_failed_parent import render as failed_actions

                failed_actions(window, snapshot, candidate, layout, guidance, action)
        if candidate in completed and not running:
            from diffeoforge.desktop.guided_accepted_fit import render as accepted_fit

            accepted_fit(window, candidate.candidate_id, layout,
                         guidance.get("accepted_fits", {}).get(candidate.candidate_id)
                         if decision is not True else None)
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
                regressed = [name for name, row in subjects.items()
                             if row.get("refinement_guard", {}).get("outcome") == "regression"]
                warning = QLabel(
                    "Joint fitting worsened agreement compared with your accepted individual "
                    "fit(s): " + ", ".join(regressed) + ". Inspect these forms before approval."
                    if snapshot.attachment_comparison.get("joint_initialization") else
                    "This test worsened whole-shape agreement. Keep the earlier "
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
            if (decision is not True and (decision is False or has_start)
                    and (valid or has_start) and not unresolved
                    and (guidance["preferred"] == method or has_start or info["phase"] == "joint")):
                _recovery(window, snapshot, candidate, layout, guidance)
            regional = bool(snapshot.attachment_comparison.get("regional_objective"))
            if decision is True and regional:
                note = QLabel("This fit is saved as suitable for this specimen. Further "
                              "refinement is optional. The shared atlas setup still needs "
                              "its own check.")
                note.setWordWrap(True)
                layout.addWidget(note)
                optional = QWidget()
                optional_layout = QVBoxLayout(optional)
                _recovery(window, snapshot, candidate, optional_layout, guidance, optional=True)
                disclosure = InfoDisclosure("Optional further refinement", optional)
                _set_action_emphasis(disclosure.toggle_button, False)
                disclosure.toggle_button.setToolTip(
                    "Show optional adjustments. Opening these controls starts no fit.")
                layout.addWidget(disclosure)
            if decision is True and info["phase"] != "joint" and not regional:
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
        comparison = guidance.get("provisional_comparison") or {}
        if len(approved) != 2 and comparison.get("eligible"):
            note = QLabel(comparison["explanation"])
            note.setObjectName("status")
            note.setWordWrap(True)
            window.content_layout.addWidget(note)
            if comparison["available"]:
                button = action(
                    window.content_layout,
                    "No clear winner yet → compare another form provisionally (2 tests)",
                    "compare_unresolved",
                    None,
                )
                button.setToolTip("Next selected form: " + comparison["target"])
                _set_action_emphasis(button, False)
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


def _recovery(window, snapshot, candidate, layout, guidance, *, optional=False):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis
    from diffeoforge.pilot_recovery import DESCRIPTIONS
    from diffeoforge.pilot_regions import SYMPTOMS

    identifier = candidate.candidate_id
    heading = QLabel(
        "Optional: what would you like to improve further?"
        if optional else "This configuration has not passed this form. What needs improvement?")
    heading.setWordWrap(True)
    heading.setObjectName("status")
    layout.addWidget(heading)
    symptoms = QComboBox()
    symptoms.setAccessibleName("What is wrong with " + candidate.label + "?")
    for key, label in SYMPTOMS.items():
        symptoms.addItem(label, key)
    saved_feedback = guidance.get("feedback", {}).get(identifier) or {}
    recorded = saved_feedback.get("feedback") or {}
    regions = saved_feedback.get("problem_regions", {})
    first = next((r for rows in regions.values() for r in rows), None)
    symptom = recorded.get("symptom", "unsure")
    if symptom == "unsure" and first:
        symptom = first["symptom"]
    symptoms.setCurrentIndex(symptoms.findData(
        symptom))
    layout.addWidget(symptoms)
    explanation = QLabel()
    explanation.setWordWrap(True)
    explanation.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
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
    from diffeoforge.desktop.guided_diagnosis import render as render_diagnosis

    diagnostics = render_diagnosis(window, snapshot, identifier, layout, guidance)

    def update(*_):
        selected = alternatives.currentData()
        local = any(regions.values()) and symptoms.currentData() not in {
            "alignment", "topology", "view"}
        request = ("goal:" + selected if selected else
                   "regional:" + symptoms.currentData() if local else symptoms.currentData())
        proposed = guidance["proposals"][identifier][request]
        state.clear()
        state.update(proposed)
        state["request"] = request
        explanation.setText(
            f"{proposed['reason']} "
            + ("Reuse a compatible saved single-form deformation on the same basis. "
               if proposed['initialization'] == 'learned'
               else "Keep saved control points and momenta; add zero-momentum controls. "
               if proposed['initialization'] == 'nested'
               else "Retain the saved deformation and add a local residual field. "
               if proposed['initialization'] == 'residual'
               else "This changes the deformation basis or method and needs a fresh start. ")
            + (f"Keep all fitting settings; allow up to {proposed['optimization_iterations']} "
               "new iterations from that saved field, with new optimizer history. "
               if proposed['numerical_extension'] else "")
            + ("Prepare one protected regional test, then inspect it. Regional constraints "
               "remain explicit; a shared cohort objective needs separate validation. "
               if proposed['goal'] == 'regional' else
               f"Prepare one test here, then inspect it. If suitable: "
               f"{proposed['remaining_checks']} other form(s), then a joint check. ")
            + "Earlier results stay saved."
            if proposed["available"] else
            proposed.get("blocked_reason", "This unchanged combination has already been tested. "
                         "Inspect saved alternatives or select another adjustment below; "
                         "no repeat is prepared.")
        )
        prepare.setText(proposed["title"] + " · prepare 1 trial on 1 specimen")
        prepare.setEnabled(proposed["available"])
        prepare.setVisible(proposed["available"])
        _set_action_emphasis(prepare, proposed["available"])
        data = guidance.get("feedback", {}).get(identifier)
        if data and data["needs_direction"]:
            prepare.setEnabled(False)
            _set_action_emphasis(prepare, False)
            explanation.setText(
                "Tell us whether the last change helped, or choose an earlier starting fit above. "
                "This prevents another change from building blindly on a worse attempt.")
        if diagnostics and not proposed["available"]:
            diagnostics.toggle_button.setChecked(True)

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
        other_proposal = guidance["proposals"][identifier]["other_method"]
        data = guidance.get("feedback", {}).get(identifier)
        other.setEnabled(other_proposal["available"] and not (data and data["needs_direction"]))
        if not other_proposal["available"]:
            other.setText("Inspect saved fit with the other method")
            reference = next((r.get("fit") for r in reversed(guidance["cases"])
                if r["method"] != other_proposal["anchor"]["method"]
                and r["target"] == other_proposal["target"] and r.get("fit")), None) \
                if other_proposal.get("anchor") else None
            other.setEnabled(bool(reference))
            other.setVisible(bool(reference))
            other.clicked.connect(lambda: window._open_guided_saved_fit(reference))
        else:
            other.clicked.connect(lambda: window._start_pilot(
                adaptive=False, guided_action=("adaptive_recover", identifier, "other_method")
            ))
        other.setStyleSheet("QPushButton { border: 1px solid #789994; "
                           "border-radius: 4px; padding: 8px; }")
        layout.addWidget(other)
    from diffeoforge.desktop.guided_input_checks import input_checks

    saved = guidance.get("feedback", {}).get(identifier) or {}
    reference = saved.get("selected") or saved.get("comparison") or guidance.get("preference")
    input_checks(window, layout, guidance, reference)
