"""Prominent, non-computing escape route from a rejected joint fit or retry."""

from PySide6.QtWidgets import QLabel, QPushButton


def render(window, identifier, layout, data):
    if not data:
        return
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis

    note = QLabel(
        "Accepted single-form fit selected for further improvements: "
        if data["selected"] else "Your accepted single-form fit is still saved: ")
    note.setText(note.text() + data["label"] + "\n" + data["target"]
                 + ". Returning selects its saved deformation and starts no computation. "
                 "It does not approve the joint fit.")
    note.setWordWrap(True)
    note.setObjectName("acceptedFitRecovery")
    layout.addWidget(note)
    inspect = QPushButton("Inspect accepted single-form fit")
    inspect.clicked.connect(lambda: window._open_guided_saved_fit(data["reference"]))
    layout.addWidget(inspect)
    if not data["selected"]:
        restore = QPushButton("Return to accepted single-form fit · no computation")
        restore.setProperty("acceptedFitRecovery", True)
        restore.setAccessibleName(restore.text())
        _set_action_emphasis(restore, True)
        restore.clicked.connect(lambda: window._start_pilot(
            adaptive=False, guided_action=("adaptive_restore_accepted", identifier,
                                           data["reference"])))
        layout.addWidget(restore)
