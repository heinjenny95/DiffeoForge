"""Nonmodal accepted-state review, while the native optimizer waits in memory."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.pilot_live_review import preview_models, read_review, request_review_action


class PilotLiveReviewPanel(QFrame):
    def __init__(self, parent=None, *, active=lambda: True):
        super().__init__(parent)
        self.setObjectName("card")
        self.run = self.bound = None
        self.active = active
        self._generation = None
        self._sent = False
        layout = QVBoxLayout(self)
        self.title = QLabel("Intermediate fit review")
        self.title.setObjectName("pilotReviewTitle")
        title_font = self.title.font()
        title_font.setBold(True)
        self.title.setFont(title_font)
        layout.addWidget(self.title)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.canvas = CalibrationComparisonCanvas3D()
        self.canvas.originalDetailRequested.connect(self._load_detail)
        layout.addWidget(self.canvas)
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        actions = QHBoxLayout()
        self.continue_button = QPushButton("Allow another 10 minutes")
        self.finish_button = QPushButton("Finish fitting → check this result")
        self.finish_button.setObjectName("primary")
        self.continue_button.setStyleSheet(
            "QPushButton { border: 1px solid #789994; border-radius: 4px; padding: 8px; }"
        )
        self.continue_button.setToolTip(
            "Continue the same optimizer. Time spent reviewing does not use this allowance."
        )
        self.finish_button.setToolTip(
            "End optimization at this accepted state. Export and geometry checks still follow."
        )
        self.continue_button.clicked.connect(lambda: self._decide("continue"))
        self.finish_button.clicked.connect(lambda: self._decide("finish"))
        actions.addWidget(self.continue_button)
        actions.addWidget(self.finish_button)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.hide()

    @property
    def waiting(self):
        return self.bound is not None and not self._sent

    def set_run(self, run):
        self.clear()
        self.run = Path(run)

    def clear(self):
        self.loader.cancel()
        self.run = self.bound = self._generation = None
        self._sent = False
        self.canvas.clear()
        self.hide()

    def poll(self):
        if self.run is None:
            return
        if not self.active():
            self.clear()
            return
        try:
            # All mesh parsing and hashing is performed in the loader worker.
            live_path = self.run / "output/pilot-review/live.json"
            if not live_path.is_file():
                return
            raw = live_path.read_bytes()
            import json

            if len(raw) > 4096:
                raise ValueError("Oversized intermediate review pointer")
            live = json.loads(raw)
            if live.get("status") != "waiting":
                if self.bound is not None:
                    self.bound = None
                    self.hide()
                return
            generation = live.get("generation"), live.get("nonce"), live.get("receipt_sha256")
            if generation == self._generation:
                return
            self._generation = generation
            self._sent = False
            self.bound = None
            self.canvas.clear()
            self.note.setText(
                "Optimization is paused at an accepted state. Loading its bound preview…"
            )
            self.continue_button.setEnabled(False)
            self.finish_button.setEnabled(False)
            self.show()

            def load():
                bound = read_review(self.run)
                if bound is None:
                    raise ValueError("The intermediate review is no longer waiting")
                return bound, preview_models(bound)

            self.loader.request_operation(generation, load)
        except (OSError, ValueError, KeyError) as error:
            self._failed(None, str(error))

    def _loaded(self, key, value):
        full_detail = isinstance(key, tuple) and len(key) == 2 and key[0] == "detail"
        if (key[1] if full_detail else key) != self._generation:
            return
        self.bound, models = value
        self.canvas.set_models(*models)
        if full_detail:
            self.canvas.original_detail.setChecked(True)
        row = self.bound["receipt"]
        self.title.setText(f"Review after {row['active_seconds'] / 60:.1f} minutes of fitting")
        self.note.setText(
            f"Paused after {row['accepted_updates']} accepted "
            + ("step" if row["accepted_updates"] == 1 else "steps")
            + "; optimizer kept in memory. "
            "Are the projections captured and the overall shape right? Small surface differences "
            "can remain. Finish fitting to export and check this state, or give it another "
            "10 minutes. This preview is not an approved final result."
        )
        self.continue_button.setEnabled(True)
        self.finish_button.setEnabled(True)

    def _load_detail(self):
        if self.bound is None or self._sent:
            return
        bound = self.bound
        self.continue_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self.note.setText("Loading full detail by request; optimization remains paused…")
        self.loader.request_operation(
            ("detail", self._generation), lambda: (bound, preview_models(bound, full_detail=True))
        )

    def _failed(self, _key, message):
        self.bound = None
        self.canvas.clear()
        self.note.setText(
            "Intermediate preview unavailable: "
            + message
            + ". The optimizer remains paused. Cancel safely is still available."
        )
        self.continue_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self.show()

    def _decide(self, action):
        if self.bound is None or self._sent or not self.active():
            return
        try:
            request_review_action(self.bound, action)
        except (OSError, ValueError, KeyError) as error:
            self._failed(None, str(error))
            return
        self._sent = True
        self.continue_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self.note.setText(
            "Continuing the same optimizer for another 10 active minutes…"
            if action == "continue"
            else "Finishing at this accepted state. Export and geometry checks follow; "
            "no more fitting."
        )
