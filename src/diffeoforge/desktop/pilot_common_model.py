"""Visible shared-model recovery, separate from optional individual repairs."""
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from diffeoforge.desktop.info_disclosure import InfoDisclosure


def pin_recovery(window, snapshot, choice):
    """Keep the candidate's next preparation outside scrolling repair/history tools."""
    if (not choice or choice.get("mode") not in
            {"candidate_refine", "broad_detail", "detail_pending"}
            or not choice.get("available") or window._guided_footer_action
            or len(snapshot.candidates) != 1):
        return
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    identifier = snapshot.candidates[0].candidate_id
    window.next_step_button.setText(choice["label"])
    window.next_step_button.setVisible(True)
    window.next_step_button.setEnabled(True)
    window.next_step_button.setToolTip("Prepare this separate common-setting test. "
        "Existing fits and approvals stay saved; fitting starts only with Run.")
    window._guided_footer_action = (
        snapshot.study_directory,
        "adaptive_multiscale_detail" if choice["mode"] == "detail_pending"
        else "adaptive_common_continue", identifier)
    _set_action_emphasis(window.next_step_button, True)


def pin_revision(window, snapshot, guidance):
    """Keep explicit adoption of a reviewed common candidate in the fixed footer."""
    if window._guided_footer_action or len(snapshot.candidates) != 1:
        return
    identifier = snapshot.candidates[0].candidate_id
    if (snapshot.visual_reviews.get(identifier) is not True
            or not guidance.get("common_revision", {}).get(identifier)):
        return
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    window.next_step_button.setText("Use approved common settings → check next form")
    window.next_step_button.setVisible(True)
    window.next_step_button.setEnabled(True)
    window.next_step_button.setToolTip(
        "Explicitly adopt this reviewed candidate as the common model and prepare its next "
        "check. Your good individual fits and earlier decisions stay saved. Fitting starts "
        "only with Run.")
    window.status.setText(
        "Suitable fit saved. Use these approved settings as the common model, then check "
        "the next form.")
    window._guided_footer_action = (
        snapshot.study_directory, "adaptive_adopt_common_model", identifier)
    _set_action_emphasis(window.next_step_button, True)


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
    title = QLabel("Continue toward one common model")
    title.setObjectName("sectionTitle")
    layout.addWidget(title)
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
    if (choice["mode"] in {"candidate_refine", "broad_detail", "detail_pending"} and pinned
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
