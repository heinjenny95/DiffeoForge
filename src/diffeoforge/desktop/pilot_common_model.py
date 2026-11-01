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
