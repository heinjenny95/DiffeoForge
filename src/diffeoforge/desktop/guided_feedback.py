"""Visible relative feedback and recoverable inspected starting-fit choices."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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


def prepare_context(snapshot, identifier):
    """Called in the existing background viewer preparation scope."""
    from diffeoforge.desktop.reference_calibration_dialog import collect_calibration_qc_pairs
    from diffeoforge.guided_feedback import presentation, verify_reference

    data = presentation(snapshot, identifier)
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

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        baseline = data["comparison"]
        label = next((r["label"] for r in data["choices"] if r["reference"] == baseline),
                     baseline["method"].title())
        title = QLabel("Change compared with the starting fit: " + label)
        title.setWordWrap(True)
        layout.addWidget(title)
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
        self._ready = False
        self.buttons.buttonClicked.connect(self._update)
        self.save.clicked.connect(lambda: self.saveRequested.emit(self.decision))
        previous = data.get("feedback")
        if previous:
            self.outcomes[previous["outcome"]].setChecked(True)
            self.note.setText(previous["note"])
            self.symptom.setCurrentIndex(self.symptom.findData(previous.get("symptom", "unsure")))
        self.set_ready(False)

    @property
    def decision(self):
        outcome = next((k for k, b in self.outcomes.items() if b.isChecked()), None)
        return (dict(outcome=outcome, comparison=self.data["comparison"], note=self.note.text(),
                     symptom=self.symptom.currentData())
                if self._ready and outcome else None)

    def set_ready(self, ready):
        self._ready = ready
        for button in self.outcomes.values():
            button.setEnabled(ready)
        self.note.setEnabled(ready)
        self.symptom.setEnabled(ready)
        self._update()

    def _update(self, *_):
        self.save.setEnabled(self.decision is not None)


def render_starting_fits(window, snapshot, identifier, layout, data):
    """The escape route is a visible button; no optimizer or automatic approval."""
    if not data or not data["choices"]:
        return
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    selected = data["selected"]
    selection = next((r for r in data["choices"] if r["reference"] == selected), None)
    feedback = data.get("feedback")
    if feedback and feedback["outcome"] in {"worse", "same", "unsure"}:
        label = QLabel(
            "This attempt did not improve the starting fit. Further suggestions use "
            "that earlier starting point; this result remains saved.")
        label.setWordWrap(True)
        layout.addWidget(label)
    if selection:
        caption = QLabel("Starting point: " + selection["label"])
        caption.setWordWrap(True)
        caption.setObjectName("guidedStartingFit")
        layout.addWidget(caption)
        if not selection["current"]:
            inspect_start = QPushButton("Inspect retained starting fit")
            inspect_start.clicked.connect(lambda: window._open_guided_saved_fit(selected))
            layout.addWidget(inspect_start)
        if selection["approved"] and not selection["current"]:
            blocked = data.get("joint_blocked")
            if blocked:
                note = QLabel(blocked)
                note.setWordWrap(True)
                note.setObjectName("jointRepeatBlocked")
                layout.addWidget(note)
            use = QPushButton("Use reviewed starting fit → check remaining forms")
            use.setEnabled(not blocked)
            use.setToolTip(blocked or "")
            _set_action_emphasis(use, not blocked)
            use.clicked.connect(lambda: window._start_pilot(
                adaptive=False, guided_action=("adaptive_confirm_start", identifier, None)))
            layout.addWidget(use)
    same_method = [r for r in data["choices"] if not r["current"] and
                   r["reference"]["method"] ==
                   snapshot.attachment_comparison["methods"][identifier]]
    if same_method:
        first = min(same_method, key=lambda r: r.get("trial_index", 0))["reference"]
        if first != selected:
            inspect_first = QPushButton("Inspect first fit on this form")
            inspect_first.clicked.connect(lambda: window._open_guided_saved_fit(first))
            layout.addWidget(inspect_first)
            restore_first = QPushButton("Return to first fit as starting point")
            restore_first.clicked.connect(lambda: window._start_pilot(adaptive=False,
                guided_action=("adaptive_select_start", identifier, first)))
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
            " · suitable" if choice["approved"] else " · inspected, not approved"))
        caption.setWordWrap(True)
        body.addWidget(caption)
        actions = QHBoxLayout()
        inspect = QPushButton("Inspect")
        inspect.setProperty("startingFitDirectory", choice["reference"]["directory"])
        inspect.clicked.connect(lambda _checked=False, r=choice["reference"]:
                                window._open_guided_saved_fit(r))
        actions.addWidget(inspect)
        select = QPushButton("Use as starting fit")
        select.setProperty("startingFitDirectory", choice["reference"]["directory"])
        select.setEnabled(choice["reference"] != selected)
        select.clicked.connect(lambda _checked=False, r=choice["reference"]:
            window._start_pilot(adaptive=False,
                               guided_action=("adaptive_select_start", identifier, r)))
        actions.addWidget(select)
        body.addLayout(actions)
        rows.addWidget(row)
    panel.hide()
    toggle.toggled.connect(panel.setVisible)
    layout.addWidget(panel)


def render_feedback(window, snapshot, identifier, layout, data):
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
