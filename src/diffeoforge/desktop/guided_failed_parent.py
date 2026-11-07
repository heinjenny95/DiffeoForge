"""A numerical failure does not hide the trusted fit or imply an optimizer restore."""

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton


def render(window, snapshot, candidate, layout, guidance, action):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis
    from diffeoforge.pilot_regions import SYMPTOMS

    identifier = candidate.candidate_id
    evidence = guidance.get("failed_parents", {}).get(identifier) or {}
    reference = evidence.get("reference")
    if not reference:
        return
    if identifier not in guidance.get("guard_failures", {}):
        note = QLabel(evidence["reason"])
        note.setWordWrap(True)
        layout.addWidget(note)
    inspect = QPushButton("Inspect retained earlier fit")
    _set_action_emphasis(inspect, False)
    inspect.clicked.connect(lambda: window._open_guided_saved_fit(reference))
    layout.addWidget(inspect)
    if not evidence.get("available"):
        return
    proposals = guidance.get("failed_proposals", {}).get(identifier) or {}
    selector = QComboBox()
    selector.addItem("Choose a different test from the retained fit…", None)
    for request, proposal in proposals.items():
        if proposal.get("available"):
            label = proposal["title"]
            if request.startswith("regional:"):
                label += " · " + SYMPTOMS[request.split(":", 1)[1]]
            selector.addItem(label, request)
    layout.addWidget(selector)
    reason = QLabel(
        "Preparing creates a new test only. Run it separately after reviewing the plan."
    )
    reason.setWordWrap(True)
    layout.addWidget(reason)
    prepare = action(
        layout,
        "Prepare different test from retained fit",
        "recover_from_retained",
        identifier,
        available=False,
    )
    # Keep the disabled control visible: the explicit choice, not a hidden action, is missing.
    prepare.show()
    prepare.setEnabled(False)
    _set_action_emphasis(prepare, False)

    def ready():
        request = selector.currentData()
        proposal = proposals.get(request)
        return bool(
            proposal
            and proposal.get("available")
            and window._worker is None
            and not window._restoring_search
            and all(c.status in {"completed", "failed", "interrupted"} for c in snapshot.candidates)
        )

    def changed():
        request = selector.currentData()
        proposal = proposals.get(request)
        prepare.setEnabled(ready())
        reason.setText(
            proposal["reason"]
            if proposal
            else "Choose a different adjustment. The failed field is never restored."
        )

    def selected_prepare():
        if ready():
            window._start_pilot(
                adaptive=False,
                guided_action=(
                    "adaptive_recover_from_retained",
                    identifier,
                    selector.currentData(),
                ),
            )

    # The generic closure has goal=None; this explicit action binds the selected request.
    prepare.clicked.disconnect()
    prepare.clicked.connect(selected_prepare)
    selector.currentIndexChanged.connect(changed)
