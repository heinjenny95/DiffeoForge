"""Prepare an optional fixed-basis check alongside the normal atlas setup."""

from __future__ import annotations

import shlex
import sys
from threading import Event

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.reference_pilot_holdout import prepare_pilot_holdout


class PilotHoldoutCheckDialog(QDialog):
    """Prepare selected non-pilot surfaces without starting any computation."""

    def __init__(self, config_path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pre-atlas held-out check")
        self.resize(580, 240)
        self._cancelled = Event()
        layout = QVBoxLayout(self)
        details = QLabel(
            "Prepare a short registration check on up to three shapes outside the saved "
            "pilot history. The saved pilot template and control points stay fixed. "
            "This checks how the pilot basis fits new shapes before joint optimization."
        )
        details.setWordWrap(True)
        layout.addWidget(details)
        self.status = QLabel("Verifying the approved pilot and selecting held-out surfaces…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.command = QLineEdit()
        self.command.setReadOnly(True)
        self.command.setAccessibleName("Explicit CLI command for the prepared check")
        self.command.hide()
        layout.addWidget(self.command)
        buttons = QHBoxLayout()
        self.copy = QPushButton("Copy CLI command")
        self.copy.clicked.connect(self._copy)
        self.copy.hide()
        self.close_button = QPushButton("Cancel preparation")
        self.close_button.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(self.copy)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self._loader = PreviewMeshLoader(self)
        self._loader.loaded.connect(self._prepared)
        self._loader.failed.connect(self._failed)
        self.finished.connect(self._cancelled.set)
        self.finished.connect(self._loader.cancel)
        cancelled = self._cancelled
        self._loader.request_operation(
            config_path, lambda: prepare_pilot_holdout(config_path, cancelled=cancelled),
        )

    @Slot(object, object)
    def _prepared(self, _source, prepared):
        path = str(prepared.run_directory)
        quoted = (
            "'" + path.replace("'", "''") + "'" if sys.platform == "win32" else shlex.quote(path)
        )
        self.status.setText(
            f"Prepared {len(prepared.specimens)} specimens for up to "
            f"{prepared.maximum_iterations} iterations. No registration has started."
            f"\n\n{', '.join(prepared.specimens)}\n\n"
            "To run this check, use the command below in a DiffeoForge CLI environment."
        )
        self.command.setText(f"diffeoforge execute {quoted}")
        self.command.show()
        self.copy.show()
        self.close_button.setText("Close")

    @Slot(object, str)
    def _failed(self, _source, error):
        self.status.setText(f"Held-out check unavailable. {error}")
        self.close_button.setText("Close")

    @Slot()
    def _copy(self):
        QApplication.clipboard().setText(self.command.text())
