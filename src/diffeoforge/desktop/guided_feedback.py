"""Visible relative feedback and recoverable inspected starting-fit choices."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.guided_feedback import OUTCOMES
from diffeoforge.pilot_regions import SYMPTOMS

MARK_RETENTION_HINT = (
    "Deleting a red mark does not protect that area. Add a green mark to keep it unchanged."
)


def _starting_choice_options(data):
    """Name both verified alternatives without ranking either scientific result."""
    pending = data.get("starting_fit_choice") or data
    choices = data.get("choices", ())
    result = []
    for role, title, reference in (
        ("latest", "Latest fit", pending["latest"]),
        ("comparison", "Earlier comparison", pending["comparison"]),
    ):
        choice = next((r for r in choices if r["reference"] == reference), None)
        trial = choice.get("trial_index") if choice else None
        label = (f"{reference['method'].title()} · Test {trial}" if trial is not None else
                 pending.get(role + "_label") or
                 next((r["label"] for r in choices if r["reference"] == reference),
                      reference["method"].title()))
        result.append((role, title, label, reference))
    return tuple(result)


def _starting_choice_message(pending):
    return ("You rated the latest fit Better, but its checks need review: "
            + "; ".join(reason.rstrip(".") for reason in pending["reasons"]) + ". "
            "Choose and inspect the exact fit to continue from. Neither fit is selected "
            "automatically; this choice does not approve its anatomy or numerical checks.")


class StartingFitChoiceDialog(QDialog):
    """A source-inspection handoff only; closing this dialog records no preference."""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose starting fit")
        self.resize(620, 330)
        self.chosen_reference = None
        self.restore_partial = False
        layout = QVBoxLayout(self)
        pending = data.get("starting_fit_choice") or data
        warning = QLabel(_starting_choice_message(pending))
        warning.setObjectName("startingFitChoiceWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.choice_buttons = []
        for role, title, label, reference in _starting_choice_options(data):
            button = QPushButton(f"Inspect {title.lower()} · {label}…")
            button.setObjectName("secondary")
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setProperty("startingFitRole", role)
            button.clicked.connect(lambda _checked=False, r=reference, latest=role == "latest":
                                   self._choose(r, latest))
            self.choice_buttons.append(button)
            layout.addWidget(button)
        hint = QLabel(MARK_RETENTION_HINT + " Review suggested green areas before saving.")
        hint.setWordWrap(True)
        hint.setObjectName("redGreenRetentionHint")
        layout.addWidget(hint)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _choose(self, reference, latest):
        self.chosen_reference = reference
        self.restore_partial = latest
        self.accept()


def choose_starting_fit(window, data):
    """Open the normal verified saved-fit editor, without selecting or fitting here."""
    pending = data.get("starting_fit_choice") or data
    dialog = StartingFitChoiceDialog(data, window)
    if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen_reference is not None:
        window._open_guided_working_fit(pending["identifier"], dialog.chosen_reference,
                                        restore_partial=dialog.restore_partial,
                                        expected_starting_choice=pending)


def render_starting_choice(window, identifier, layout, data):
    pending = data["starting_fit_choice"]
    warning = QLabel(_starting_choice_message(pending))
    warning.setObjectName("startingFitChoiceWarning")
    warning.setWordWrap(True)
    layout.addWidget(warning)
    for role, title, label, reference in _starting_choice_options(data):
        button = QPushButton(f"Inspect {title.lower()} · {label}…")
        button.setObjectName("secondary")
        button.setAutoDefault(False)
        button.setProperty("startingFitRole", role)
        button.clicked.connect(lambda _checked=False, r=reference, latest=role == "latest":
            window._open_guided_working_fit(identifier, r, restore_partial=latest,
                                            expected_starting_choice=pending))
        layout.addWidget(button)
    hint = QLabel(MARK_RETENTION_HINT)
    hint.setObjectName("redGreenRetentionHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)


def prepare_context(snapshot, identifier, *, common_origin=None):
    """Called in the existing background viewer preparation scope."""
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs
    from diffeoforge.desktop.saved_fit_comparison import common_seed_source, trial_label
    from diffeoforge.guided_feedback import common_review, presentation, verify_reference

    data = presentation(snapshot, identifier)
    if data and common_origin is not None:
        data["common_review"] = common_review(snapshot, identifier, origin=common_origin)
    common = (data or {}).get("common_review")
    if common:
        from diffeoforge.desktop.common_review_metrics import sampled_fit_label

        current = next(c for c in snapshot.candidates if c.candidate_id == identifier)
        seed = common["numerical_seed"]
        seed_label = None
        if seed:
            parent = common_seed_source(seed)
            candidate = next(c for c in parent.candidates if c.candidate_id == seed["candidate_id"])
            seed_label = trial_label(parent, candidate)
        data["common_review"] = dict(
            common, current_label=trial_label(snapshot, current), seed_label=seed_label,
            current_distances=sampled_fit_label(current, common["current"]["target"]))
        data["require_fit_decision"] = identifier not in snapshot.visual_reviews
        return data
    if data and data["comparison"]:
        ref = data["comparison"]
        parent = verify_reference(ref)
        candidate = next(c for c in parent.candidates if c.candidate_id == ref["candidate_id"])
        pair = next(p for p in collect_calibration_qc_pairs(parent.study_directory, candidate)
                    if p.original_path.name == ref["target"] and p.required)
        data["comparison_pair_id"] = pair.pair_id
        data["comparison_reconstruction_path"] = str(pair.reconstruction_path)
        data["comparison_reconstruction_sha256"] = pair.reconstruction_sha256
    return data


class GuidedFeedbackControls(QWidget):
    saveRequested = Signal(object)

    def __init__(self, data, parent=None, *, visible_reference=False):
        super().__init__(parent)
        self.data = data
        self.rating_reference = None if visible_reference else data["comparison"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        if self.rating_reference:
            label = next((r["label"] for r in data["choices"]
                          if r["reference"] == self.rating_reference),
                         self.rating_reference["method"].title())
            self.title.setText("Change compared with the starting fit: " + label)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.buttons = QButtonGroup(self)
        self.outcomes = {}
        grid = QGridLayout()
        for index, (key, text) in enumerate(OUTCOMES.items()):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton { background: #f2f8f6; border: 1px solid #cee3dd; "
                "border-radius: 6px; min-height: 28px; padding: 2px 10px; }"
                "QPushButton:checked { background: #167c6b; border-color: #167c6b; color: white; }"
                "QPushButton:disabled { color: #78918d; background: #f2f5f4; }"
            )
            self.buttons.addButton(button)
            self.outcomes[key] = button
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        self.symptom = QComboBox()
        self.symptom.setAccessibleName("What still needs improvement?")
        for key, text in SYMPTOMS.items():
            self.symptom.addItem(text, key)
        self.symptom.setCurrentIndex(self.symptom.findData("unsure"))
        layout.addWidget(self.symptom)
        self.note = QLineEdit()
        self.note.setAccessibleName("What changed or still needs improvement?")
        self.note.setPlaceholderText("What changed or still needs work? (optional)")
        self.note.setMaxLength(2000)
        layout.addWidget(self.note)
        self.save = QPushButton("Save feedback → next steps")
        self.save.setObjectName("primary")
        self.save.setEnabled(False)
        layout.addWidget(self.save)
        mark_hint = QLabel(MARK_RETENTION_HINT)
        mark_hint.setWordWrap(True)
        mark_hint.setObjectName("redGreenRetentionHint")
        layout.addWidget(mark_hint)
        if data.get('require_fit_decision'):
            self.save.hide()
            hint = QLabel("Rate the two visible fits, then decide whether the common fit "
                          "is suitable. "
                          "Hide the comparison to assess the common fit on its own."
                          if visible_reference else
                          "Choose how this changed, then Suitable fit or Needs improvement "
                          "below. Both decisions are saved together.")
            hint.setWordWrap(True)
            hint.setObjectName('commonFitDecisionHint')
            layout.addWidget(hint)
        self._ready = False
        self.buttons.buttonClicked.connect(self._update)
        self.save.clicked.connect(lambda: self.saveRequested.emit(self.decision))
        previous = data.get("feedback")
        if previous and not visible_reference:
            self.outcomes[previous["outcome"]].setChecked(True)
            self.note.setText(previous["note"])
            self.symptom.setCurrentIndex(self.symptom.findData(previous.get("symptom", "unsure")))
        self.set_ready(False)

    @property
    def decision(self):
        outcome = next((k for k, b in self.outcomes.items() if b.isChecked()), None)
        return (dict(outcome=outcome, comparison=self.rating_reference, note=self.note.text(),
                     symptom=self.symptom.currentData())
                if self._ready and outcome and self.rating_reference is not None else None)

    def bind_displayed_reference(self, reference, label):
        self.rating_reference = reference
        self.title.setText("How does the common-model fit on the left compare with " + label + "?"
                           if reference else "Choose a reviewed fit to rate the difference."
                           if label else
                           "Show a saved comparison to rate the difference between fits.")

    def set_ready(self, ready):
        self._ready = ready
        for button in self.outcomes.values():
            button.setEnabled(ready)
        self.note.setEnabled(ready)
        self.symptom.setEnabled(ready)
        self._update()

    def _update(self, *_):
        self.save.setEnabled(self.decision is not None)


def render_starting_fits(window, snapshot, identifier, layout, data, *, edit_current=False):
    """The escape route is a visible button; no optimizer or automatic approval."""
    if not data or not data["choices"]:
        return
    if data.get("starting_fit_choice"):
        return  # The pending decision is already visible above the method cards.
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    selected = data["selected"]
    retention = data.get("retention_context")
    if retention:
        note = QLabel(retention["reason"])
        note.setWordWrap(True)
        note.setObjectName("status" if retention["available"]
                           and retention["automatic_start_allowed"] else "statusWarning")
        layout.addWidget(note)
    selection = next((r for r in data["choices"] if r["reference"] == selected), None)
    feedback = data.get("feedback")
    if (feedback and not feedback.get("common_review")
            and feedback["outcome"] in {"worse", "same", "unsure"}):
        label = QLabel(
            "This attempt did not improve the starting fit. Further suggestions use "
            "that earlier starting point; this result remains saved.")
        label.setWordWrap(True)
        layout.addWidget(label)
    if selection:
        caption = QLabel("Working starting fit: " + selection["label"])
        caption.setWordWrap(True)
        caption.setObjectName("guidedStartingFit")
        layout.addWidget(caption)
        if edit_current or not selection["current"]:
            work = QPushButton("Work from this starting fit · mark / edit areas…")
            work.setObjectName("workingStartingFit")
            target = getattr(window, "_guided_review_target", None)
            _set_action_emphasis(work, not edit_current
                                 and not (target and target["kind"] == "common"))
            work.clicked.connect(lambda: window._open_guided_working_fit(identifier, selected))
            layout.addWidget(work)
        if not selection["current"]:
            inspect_start = QPushButton("Inspect retained starting fit")
            inspect_start.clicked.connect(lambda: window._open_guided_saved_fit(selected))
            layout.addWidget(inspect_start)
        if selection["approved"] and not selection["current"]:
            blocked = data.get("joint_blocked")
            following = data.get("starting_form_progress")
            if following and not following["available"]:
                blocked = following["reason"]
            if blocked:
                note = QLabel(blocked)
                note.setWordWrap(True)
                note.setObjectName("jointRepeatBlocked")
                layout.addWidget(note)
            use = QPushButton(following["label"] if following and following["available"]
                              else "Use reviewed starting fit → check remaining forms")
            use.setEnabled(not blocked)
            use.setToolTip(blocked or "")
            _set_action_emphasis(use, not blocked)
            from diffeoforge.desktop.pilot_common_model import dispatch

            use.clicked.connect(lambda: dispatch(window, following, identifier, starting=True))
            layout.addWidget(use)
    same_method = [r for r in data["choices"] if not r["current"] and
                   r["reference"]["method"] ==
                   snapshot.attachment_comparison["methods"][identifier]]
    if same_method:
        first_choice = min(same_method, key=lambda r: r.get("trial_index", 0))
        first = first_choice["reference"]
        if first != selected:
            inspect_first = QPushButton("Inspect first fit on this form")
            inspect_first.clicked.connect(lambda: window._open_guided_saved_fit(first))
            layout.addWidget(inspect_first)
            restore_first = QPushButton("Return to first fit as starting point")
            if first_choice.get("inspected", True):
                restore_first.clicked.connect(lambda: window._start_pilot(adaptive=False,
                    guided_action=("adaptive_select_start", identifier, first)))
            else:
                restore_first.setText("Inspect first fit before choosing it…")
                restore_first.clicked.connect(lambda: window._open_guided_working_fit(
                    identifier, first))
            layout.addWidget(restore_first)
    toggle = QPushButton("Choose / inspect an earlier fit…")
    toggle.setCheckable(True)
    layout.addWidget(toggle)
    panel = QFrame()
    rows = QVBoxLayout(panel)
    for choice in data["choices"]:
        row = QFrame()
        body = QVBoxLayout(row)
        caption = QLabel(choice["label"] + (
            " · suitable" if choice["approved"] else " · inspected, not approved"
            if choice.get("inspected", True) else " · numerical result; anatomical review needed"))
        caption.setWordWrap(True)
        body.addWidget(caption)
        actions = QHBoxLayout()
        inspect = QPushButton("Inspect")
        inspect.setProperty("startingFitDirectory", choice["reference"]["directory"])
        inspect.clicked.connect(lambda _checked=False, r=choice["reference"]:
                                window._open_guided_saved_fit(r))
        actions.addWidget(inspect)
        select = QPushButton("Work from this fit…")
        select.setProperty("startingFitDirectory", choice["reference"]["directory"])
        select.clicked.connect(lambda _checked=False, r=choice["reference"]:
            window._open_guided_working_fit(identifier, r))
        actions.addWidget(select)
        body.addLayout(actions)
        rows.addWidget(row)
    panel.hide()
    toggle.toggled.connect(panel.setVisible)
    layout.addWidget(panel)


def render_feedback(window, snapshot, identifier, layout, data):
    if data and data.get("common_review"):
        inspect = QPushButton("Compare saved fits and review the common-model result…")
        inspect.clicked.connect(lambda: window._open_candidate(
            next(c for c in snapshot.candidates if c.candidate_id == identifier)))
        layout.addWidget(inspect)
        return
    if not data or not data["comparison"]:
        return
    if not data["current_inspected"]:
        hint = QLabel("Inspect this fit to tell us what changed, "
                      "or choose an earlier starting fit.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return
    controls = GuidedFeedbackControls(data)
    controls.set_ready(data["current_inspected"])

    def save(decision):
        target = data["comparison"]["target"]
        decision.update(inspected_subjects=[target],
            display_scopes={target: snapshot.visual_display_scopes.get(identifier, {}).get(
                target, "previously_recorded_original_and_reconstruction_inspection")},
            comparison_displayed=False)
        window._start_pilot(adaptive=False,
                           guided_action=("adaptive_feedback", identifier, decision))

    controls.saveRequested.connect(save)
    previous = data.get("feedback")
    if previous:
        summary = QLabel("Your feedback: " + OUTCOMES[previous["outcome"]] + " · "
                         + SYMPTOMS[previous.get("symptom", "unsure")])
        summary.setWordWrap(True)
        layout.addWidget(summary)
        edit = QPushButton("Change feedback / notes…")
        edit.setCheckable(True)
        edit.toggled.connect(controls.setVisible)
        layout.addWidget(edit)
        controls.hide()
    layout.addWidget(controls)
