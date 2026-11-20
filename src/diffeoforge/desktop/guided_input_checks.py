"""Existing input/template disclosure with read-only cached structural guidance."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from diffeoforge.desktop.info_disclosure import InfoDisclosure


def input_checks(window, layout, guidance, reference):
    """Render prepared text only. Opening/selection cannot read any mesh file."""
    panel = QWidget()
    body = QVBoxLayout(panel)
    checks = QLabel(
        "Check alignment and mesh quality if either method misses the same area. "
        "Protected local trials fit marked areas directly and check transitions and the "
        "remaining shape. A visible problem does not identify a unique cause. "
        "Changed settings require renewed checks on the other pilot forms."
    )
    checks.setWordWrap(True)
    checks.setTextFormat(Qt.TextFormat.PlainText)
    body.addWidget(checks)
    hint = guidance.get("input_topology")
    if hint:
        for text in (hint["title"], hint["message"]):
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            body.addWidget(label)
        if reference:
            from diffeoforge.desktop.guided_diagnosis import inspect_inputs

            button = QPushButton("Inspect original and starting template")
            button.setAccessibleName(button.text())
            button.setStyleSheet(
                "QPushButton { border: 1px solid #789994; "
                "border-radius: 4px; padding: 8px; }"
            )
            button.clicked.connect(lambda: inspect_inputs(window, reference))
            body.addWidget(button)
    disclosure = InfoDisclosure(
        "Input and template checks",
        panel,
        expanded=bool(hint and hint.get("input_review_recommended")),
    )
    layout.addWidget(disclosure)
    return disclosure
