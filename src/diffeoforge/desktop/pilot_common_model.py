"""Visible shared-model recovery, separate from optional individual repairs."""
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from diffeoforge.desktop.info_disclosure import InfoDisclosure


def dispatch(window, following, identifier, *, starting=False):
    reuse = (following or {}).get("common_reuse") or {}
    if reuse.get("mode") == "review":
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
    diagnosis = choice.get("diagnosis")
    if diagnosis:
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
    if (choice["mode"] == "review" and target and target["kind"] == "common"
            and target["reference"] == choice["reference"]):
        return  # Use the single, permanently visible action with the exact result name.
    if choice["available"]:
        button = QPushButton(choice["label"])
        button.setObjectName("primary")
        button.clicked.connect(lambda: window._open_common_saved_fit(choice["reference"])
            if choice["mode"] == "review" else window._start_pilot(adaptive=False,
                guided_action=("adaptive_common_continue", identifier, choice["target"])))
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
    button = QPushButton("Use these approved settings as the new common model")
    button.clicked.connect(lambda: window._start_pilot(adaptive=False,
        guided_action=("adaptive_adopt_common_model", identifier, None)))
    body.addWidget(button)
    layout.addWidget(InfoDisclosure("Revise the common model explicitly…", panel))
