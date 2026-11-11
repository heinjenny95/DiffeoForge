"""Visible shared-model recovery, separate from optional individual repairs."""
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from diffeoforge.desktop.info_disclosure import InfoDisclosure

_PINNED_RECOVERY = {
    "candidate_refine", "accepted_warm", "broad_detail", "detail_pending",
    "basis", "capacity", "fresh_capacity", "continue",
}


def pin_action(window, snapshot, label, action, identifier, tooltip, *, goal=None):
    if window._guided_footer_action:
        return False
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    button = window.next_step_button
    button.setText(label)
    button.show()
    button.setEnabled(True)
    button.setToolTip(tooltip)
    window._guided_footer_action = (snapshot.study_directory, action, identifier)
    window._guided_footer_goal = goal
    _set_action_emphasis(button, True)
    return True


def pin_recovery(window, snapshot, choice, *, current_target=None):
    """Keep the candidate's next preparation outside scrolling repair/history tools."""
    if (not choice or choice.get("mode") not in _PINNED_RECOVERY
            or not choice.get("available") or window._guided_footer_action
            or len(snapshot.candidates) != 1):
        return
    identifier = snapshot.candidates[0].candidate_id
    pin_action(
        window, snapshot, choice["label"],
        "adaptive_multiscale_detail" if choice["mode"] == "detail_pending"
        else "adaptive_common_continue", identifier,
        "Prepare this common-model test. Fitting starts when you choose Run.",
        goal=choice.get("target") if choice.get("target") != current_target else None,
    )


def pin_revision(window, snapshot, guidance, target):
    """Keep explicit adoption of a reviewed common candidate in the fixed footer."""
    if window._guided_footer_action or len(snapshot.candidates) != 1:
        return
    identifier = snapshot.candidates[0].candidate_id
    if (snapshot.visual_reviews.get(identifier) is not True
            or not guidance.get("common_revision", {}).get(identifier)):
        return
    attempt = f" · {target}" if target else ""
    pin_action(
        window, snapshot, "Use approved common settings → check next form" + attempt,
        "adaptive_adopt_common_model", identifier,
        "Adopt this reviewed fit's settings and prepare the next common-model check.",
    )
    window.status.setText("This common fit is approved. The next check needs the same settings.")


def dispatch(window, following, identifier, *, starting=False):
    reuse = (following or {}).get("common_reuse") or {}
    if reuse.get("mode") in {"review", "feedback"}:
        window._open_common_saved_fit(reuse["reference"])
    else:
        window._start_pilot(adaptive=False, guided_action=(
            "adaptive_confirm_start" if starting else "adaptive_" + following["action"],
            identifier, None))


def recovery(window, layout, identifier, choice):
    """Preparation and inspection only; native execution keeps its normal button."""
    reason = QLabel(choice.get("reason", "One separate common-model check is needed. "
        "Your suitable individual fits and previous common approvals remain saved."))
    reason.setWordWrap(True)
    layout.addWidget(reason)
    capacity = choice.get("capacity_request")
    if capacity:
        note = QLabel(f"Accepted single-fit control demand: {capacity['required_controls']}. "
            f"Shared basis test: {capacity['current_controls']} → {capacity['target_count']}. "
            "Preserved field prefixes and local additions are included. All forms will use "
            "the same adopted basis; a control count alone does not guarantee matching shape.")
        note.setObjectName("commonAcceptedCapacity")
        note.setWordWrap(True)
        layout.addWidget(note)
    diagnosis = choice.get("diagnosis")
    if diagnosis:
        if diagnosis.get('marked_progress') is False:
            note = QLabel(
                "The important marked area did not improve reliably. Improvement elsewhere "
                "is not enough to propose more iterations with unchanged settings.")
            note.setObjectName("commonMarkedPlateau")
            note.setWordWrap(True)
            layout.addWidget(note)
        summary = QLabel(
            "Compared with your accepted individual fit: "
            + ("local surface differences remain. " if diagnosis["gap"] else
               "no reliable surface loss was found in these samples. ")
            + "Both surface directions and saved marked areas are checked. "
            "Your accepted fit and its approval remain saved.")
        summary.setObjectName("commonAcceptedComparison")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        technical = QLabel(
            f"Common ↔ accepted agreement P95: {diagnosis['agreement_p95']:.5g}. "
            f"Saved common-field trend: {diagnosis['trend']}. "
            f"Common controls: {diagnosis['current_controls']}. "
            "Sampled distance agreement is separate from anatomical approval.")
        technical.setWordWrap(True)
        layout.addWidget(InfoDisclosure("Measurements behind this suggestion", technical))
        number = diagnosis.get("accepted_test_number")
        name = f" · Test {number}" if number is not None else ""
        inspect = QPushButton("Inspect accepted individual fit" + name + "…")
        inspect.clicked.connect(lambda: window._open_guided_saved_fit(diagnosis["accepted"]))
        layout.addWidget(inspect)
    target = getattr(window, "_guided_review_target", None)
    if (choice["mode"] in {"review", "feedback"} and target and target["kind"] == "common"
            and target["reference"] == choice["reference"]):
        return  # Use the single, permanently visible action with the exact result name.
    pinned = getattr(window, "_guided_footer_action", None)
    action = ("adaptive_multiscale_detail" if choice["mode"] == "detail_pending"
              else "adaptive_common_continue")
    if (choice["mode"] in _PINNED_RECOVERY and pinned
            and pinned[1:] == (action, identifier)):
        return
    if choice["available"]:
        button = QPushButton(choice["label"])
        button.setObjectName("primary")
        button.clicked.connect(lambda: window._open_common_saved_fit(choice["reference"])
            if choice["mode"] in {"review", "feedback"} else window._start_pilot(adaptive=False,
                guided_action=(action, identifier, choice["target"])))
        layout.addWidget(button)


def revision(window, layout, identifier, proposed):
    panel = QWidget()
    body = QVBoxLayout(panel)
    note = QLabel(f"Explicit model revision: {proposed['checked']} / {proposed['total']} "
        "forms already match these settings. Other common-model checks are still required. "
        "All earlier suitable fits and decisions remain saved. This prepares a separate "
        "successor and does not start fitting.")
    note.setWordWrap(True)
    body.addWidget(note)
    pinned = getattr(window, "_guided_footer_action", None)
    if not pinned or pinned[1:] != ("adaptive_adopt_common_model", identifier):
        button = QPushButton("Use these approved settings as the new common model")
        button.clicked.connect(lambda: window._start_pilot(adaptive=False,
            guided_action=("adaptive_adopt_common_model", identifier, None)))
        body.addWidget(button)
    layout.addWidget(InfoDisclosure("Revise the common model explicitly…", panel))
