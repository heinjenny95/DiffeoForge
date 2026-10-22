"""Compact guided-pilot actions. Each next batch still needs an explicit Run."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.reference_guided_pilot import record


def render(window, prepared):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    snapshot = prepared.snapshot
    info = record(snapshot)
    running = window._worker is not None or window._restoring_search
    # Restore these before returning to the ordinary final qualification view.
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
        else "Check another form"
        if info["phase"] == "validate"
        else "Compare Current and Varifold"
    )
    title.setObjectName("sectionTitle")
    window.content_layout.addWidget(title)
    explanation = QLabel(
        f"One common configuration · {snapshot.plan.pilot_subject_count} pilot specimens."
        if info["phase"] == "joint"
        else f"{info['target']} · {len(snapshot.candidates)} trial(s). "
        f"Screening budget: {info['screen_trials_spent']} of {info['screen_trial_limit']} planned."
    )
    explanation.setWordWrap(True)
    window.content_layout.addWidget(explanation)
    if info["phase"] == "screen":
        why = QLabel(
            "Current uses oriented surfaces; Varifold ignores normal direction. "
            "The pilot checks which follows your surfaces more reliably."
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
        else "Run selected method · 1 specimen"
    )
    window.start_button.setVisible(bool(pending))
    window.start_button.setEnabled(not running)
    _set_action_emphasis(window.start_button, bool(pending) and not running)
    window.cancel_button.setVisible(running)
    window.cancel_button.setEnabled(running)
    window.status.setText(
        "Computing the confirmed batch…"
        if running
        else "A trial failed. Inspect details, retry, or choose an approved alternative."
        if failed
        else "Review the completed fits."
        if completed
        else "Ready. Preparing this plan has started no fits."
    )
    for candidate in failed:
        window.content_layout.addWidget(
            InfoDisclosure(
                candidate.label + " · technical failure", candidate.error or "No usable result"
            )
        )
    if running or not completed:
        return
    choice = QComboBox()
    choice.setAccessibleName("Fit to inspect")
    for candidate in completed:
        decision = snapshot.visual_reviews.get(candidate.candidate_id)
        suffix = (
            " · approved"
            if decision is True
            else " · unfit"
            if decision is False
            else " · review needed"
        )
        runtime = (candidate.metrics or {}).get("runtime_seconds")
        if runtime is not None:
            suffix += f" · {runtime / 60:.1f} min"
        if (candidate.metrics or {}).get("converged") is False:
            suffix += " · iteration limit, provisional"
        choice.addItem(candidate.label + suffix, candidate.candidate_id)
    from diffeoforge.reference_attachment_comparison import recommendation as recommend

    recommendation = recommend(snapshot)
    if recommendation and recommendation["recommended_candidate_id"]:
        choice.setCurrentIndex(max(0, choice.findData(recommendation["recommended_candidate_id"])))
    inspect = QPushButton("Inspect fit")
    _set_action_emphasis(inspect, True)
    inspect.setEnabled(not running)
    inspect.clicked.connect(
        lambda: window._open_candidate(
            next(c for c in completed if c.candidate_id == choice.currentData())
        )
    )
    row = QHBoxLayout()
    row.addWidget(choice, 1)
    row.addWidget(inspect)
    window.content_layout.addLayout(row)

    def action(label, kind, *, identifier=None, goal=None, available=True):
        button = QPushButton(label, window.content)
        enabled = not running and not unresolved and available
        button.setEnabled(enabled)
        button.setVisible(enabled)
        _set_action_emphasis(button, enabled)
        button.clicked.connect(
            lambda: window._start_pilot(
                adaptive=False, guided_action=(kind, identifier or choice.currentData(), goal)
            )
        )
        window.content_layout.addWidget(button)
        return button

    approved = [c for c in completed if snapshot.visual_reviews.get(c.candidate_id) is True]
    if info["phase"] == "joint":
        action(
            "Use reviewed joint fit → check time resolution",
            "finish_joint",
            available=len(approved) == 1,
        )
        hint = QLabel(
            "The same joint reconstruction is retained. No parameter grid runs. "
            "An iteration-limit warning remains provisional."
        )
        hint.setWordWrap(True)
        window.content_layout.addWidget(hint)
        return
    for candidate in approved:
        action(
            "Use " + candidate.label + " → check remaining forms",
            "choose",
            identifier=candidate.candidate_id,
        )
    if len(snapshot.candidates) == 2:
        covered = {r["filename"] for r in info["approved"]}
        covered.add(info["target"])
        remaining = set(info["pilot_order"]) - covered
        action(
            "Both good → compare on another form (2 trials)",
            "both_good",
            available=len(approved) == 2 and bool(remaining),
        )
        if len(approved) == 2 and not remaining:
            tie = QLabel(
                "Both methods passed the tested forms. Choose an approved method; "
                "recorded runtime can guide an efficiency choice. No visual winner is claimed."
            )
            tie.setWordWrap(True)
            window.content_layout.addWidget(tie)
    diagnostic = QWidget(window.content)
    from PySide6.QtWidgets import QVBoxLayout

    diagnostic_layout = QVBoxLayout(diagnostic)
    text = QLabel(
        "Both unfit? Check alignment, mesh quality and the starting template first. "
        "Then request one targeted change. Earlier fits stay saved; changed settings "
        "need fresh cross-checks."
    )
    text.setWordWrap(True)
    diagnostic_layout.addWidget(text)
    goals = QComboBox()
    goals.addItem("Missing local detail → finer matching scale", "detail")
    goals.addItem("Large-scale mismatch → broader deformation scale", "motion")
    goals.addItem("Overall weak fit → stronger surface-matching weight", "weight")
    diagnostic_layout.addWidget(goals)
    retry = QPushButton(f"Prepare targeted follow-up · {len(snapshot.candidates)} trial(s)")
    reviewed = all(c.candidate_id in snapshot.visual_reviews for c in completed)
    retry.setEnabled(not running and not unresolved and reviewed)
    both_bad = len(snapshot.candidates) == 2 and all(
        snapshot.visual_reviews.get(c.candidate_id) is False for c in snapshot.candidates
    )
    retry.clicked.connect(
        lambda: window._start_pilot(
            adaptive=False,
            guided_action=("both_bad" if both_bad else "adjust", None, goals.currentData()),
        )
    )
    diagnostic_layout.addWidget(retry)
    diagnostic_disclosure = InfoDisclosure("Targeted next steps", diagnostic)
    if len(snapshot.candidates) == 2:
        bad_button = QPushButton("Both unfit → check common causes", window.content)
        bad_button.setVisible(both_bad and not running)
        bad_button.setEnabled(both_bad and not running)
        _set_action_emphasis(bad_button, both_bad and not running)
        bad_button.clicked.connect(lambda: diagnostic_disclosure.toggle_button.setChecked(True))
        window.content_layout.addWidget(bad_button)
    diagnostic_disclosure.setVisible(reviewed and not unresolved)
    window.content_layout.addWidget(diagnostic_disclosure)
    unsure = QLabel(
        "Unsure? Reopen a fit, rotate it, toggle the original or show a saved alternative. "
        "Close without recording to leave the decision open."
    )
    unsure.setWordWrap(True)
    uncertain = InfoDisclosure("Unsure → help with visual assessment", unsure)
    window.content_layout.addWidget(uncertain)
