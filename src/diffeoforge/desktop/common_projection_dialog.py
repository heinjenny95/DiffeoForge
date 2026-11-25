"""Explicit bounded transfer and original-target refit, supervised by the native runner."""

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader


class CommonProjectionDialog(QDialog):
    progress = Signal(object)

    def __init__(self, parent, snapshot, choice):
        super().__init__(parent)
        from diffeoforge import pilot_common_projection as transfer

        self.snapshot = snapshot
        self.choice = choice
        self.directory = transfer.default_directory(snapshot, choice)
        self.runner = None
        self.operation = None
        self.next_action = None
        self.successor = None
        self.stage_finished = False
        self.recovery_run = None
        self.setProperty("processRecordingPilotReview", True)
        self.setWindowTitle("Transfer approved anatomy to the common model")
        self.resize(640, 290)
        layout = QVBoxLayout(self)
        title = QLabel(choice["target"])
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("heading")
        title.setWordWrap(True)
        layout.addWidget(title)
        count = choice.get("approved_region_count", 0)
        area_note = f" and {count} saved {'area' if count == 1 else 'areas'}" if count else ""
        instruction = QLabel(
            "Test the approved shape on the shared control points. "
            f"Compare the whole specimen{area_note} with the original before starting the next fit."
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName("Common fit progress")
        layout.addWidget(self.progress_bar)
        layout.addStretch()
        self.inspect = QPushButton("Compare saved anatomy…")
        self.inspect.clicked.connect(self._inspect)
        layout.addWidget(self.inspect)
        footer = QHBoxLayout()
        self.cancel_run = QPushButton("Cancel safely")
        self.cancel_run.clicked.connect(self._cancel)
        footer.addWidget(self.cancel_run)
        self.refresh_status = QPushButton("Refresh status")
        self.refresh_status.clicked.connect(self._refresh)
        self.refresh_status.hide()
        footer.addWidget(self.refresh_status)
        footer.addStretch()
        self.primary = QPushButton()
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self._dispatch)
        footer.addWidget(self.primary)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.finished.connect(self.loader.cancel)
        self.progress.connect(self._progress)
        self._refresh()

    def _start(self, operation, text, fn):
        self.operation = operation
        self.primary.hide()
        self.primary.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.inspect.setEnabled(False)
        self.refresh_status.hide()
        self.cancel_run.setVisible(self.runner is not None)
        self.cancel_run.setEnabled(self.runner is not None)
        self.close_button.setEnabled(False)
        self.status.setText(text)
        self.setProperty("processRecordingWaiting", True)
        self.loader.request_operation(operation, fn)

    def _refresh(self):
        from diffeoforge import pilot_common_projection as transfer

        self._start(
            "status",
            "Checking saved transfer steps…",
            lambda: transfer.status(self.directory) if self.directory.exists() else {},
        )

    def _show_action(self, action, label, help_text):
        self.next_action = action
        self.primary.setText(label)
        self.primary.setEnabled(action is not None)
        self.primary.setVisible(action is not None)
        self.status.setText(help_text)

    def _loaded(self, key, value):
        from diffeoforge import pilot_common_projection as transfer

        self.operation = None
        self.runner = None
        self.progress_bar.hide()
        self.setProperty("processRecordingWaiting", False)
        self.cancel_run.hide()
        self.close_button.setEnabled(True)
        self.close_button.setText("Close")
        if key == "attach":
            self.successor = value
            self.accept()
            return
        if key == "review":
            self._review(value)
            return
        if key != "status":
            if key in {"projection", "original", "save"}:
                self.stage_finished = True
            self._refresh()
            return
        projection, original = value.get("projection"), value.get("original")
        self.recovery_run = Path(value["previous_run"]) if projection == "recovery" else None
        self.refresh_status.setVisible(self.recovery_run is not None)
        ready = projection == "completed"
        self.inspect.setVisible(ready)
        self.inspect.setEnabled(ready)
        if not value:
            self._show_action(
                "prepare",
                "Prepare transfer",
                "Preparation records the approved "
                "fit, the original specimen and the common model for this test.",
            )
        elif original == "completed":
            approved = value.get("approved")
            original_check = value.get("original_retention", {})
            numerical = value.get("original_numerical", {}).get("passed") is True
            if original_check.get("status") != "comparable" or not numerical or approved is False:
                notes = [original_check.get("summary") or "Inspect the original-target fit."]
                if not numerical:
                    notes.append("The numerical checks for the original-target fit did not pass.")
                if approved is False:
                    notes.append("You rated this result as needing improvement.")
                notes.append(
                    "Return to the pilot to choose the next common fit."
                )
                self.close_button.setText("Return to pilot")
                self._show_action(None, "", " ".join(notes))
            elif value.get("can_attach") is True:
                self._show_action(
                    "attach",
                    "Use reviewed common fit",
                    "The original-target fit has your suitability review.",
                )
            else:
                self._show_action(
                    "review",
                    "Review fit to original…",
                    "Compare the original-target "
                    "fit with the approved anatomy before using it in the pilot.",
                )
        elif "running" in (projection, original):
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            self._show_action(
                "refresh",
                "Refresh status",
                "A saved transfer step is active. Its recorded status is available here.",
            )
        elif self.recovery_run is not None:
            self._show_action(
                "recover",
                "Recover stopped transfer…",
                "This transfer has no matching terminal result. If the backend is still running, "
                "wait and refresh. After a crash, confirm that its processes have stopped "
                f"before recovering the saved run.\n{self.recovery_run}",
            )
        elif projection == "verify_saved":
            self._show_action(
                "projection",
                "Check saved transfer",
                "The native transfer finished. Verify its saved result to continue.",
            )
        elif projection == "interrupted":
            self._show_action(
                "projection",
                f"Retry transfer · up to {transfer.BUDGET} iterations",
                "The previous transfer is recorded as interrupted. Retry starts a separate run.",
            )
        elif ready and value.get("can_fit_original") is not True:
            check = value.get("projection_retention", {})
            reason = check.get("summary") or "The transfer needs review."
            if value.get("projection_numerical", {}).get("passed") is not True:
                reason += " The numerical checks for the transferred field did not pass."
            self.close_button.setText("Return to pilot")
            self._show_action(
                None, "", reason + " Return to the pilot to prepare the next common fit."
            )
        elif ready:
            self._show_action(
                "original",
                "Fit original from transfer",
                "The transfer endpoint is "
                "ready for inspection. The next fit uses the original specimen as its target.",
            )
        else:
            self._show_action(
                "projection",
                f"Run transfer · up to {transfer.BUDGET} iterations",
                "The transfer uses this specimen’s approved reconstruction as the target.",
            )
        if value.get("message"):
            self.status.setText(self.status.text() + "\n" + value["message"])

    def _dispatch(self):
        from diffeoforge import pilot_common_projection as transfer
        from diffeoforge.reference_calibration_study import load_reference_calibration_study

        if self.operation:
            return
        action = self.next_action
        if action == "refresh":
            self._refresh()
        elif action == "recover":
            from diffeoforge.pilot_projection_worker import recover_projection

            run = self.recovery_run
            choice = QMessageBox.warning(
                self,
                "Confirm the transfer backend has stopped",
                "Confirm that DiffeoForge, Deformetrica, WSL and container processes have "
                f"stopped writing to this run.\n\n{run}\n\nRecovery verifies and records "
                "the terminal result. A new transfer requires a separate start.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Yes:
                self._start(
                    action,
                    "Verifying the stopped transfer…",
                    lambda: recover_projection(
                        self.directory,
                        run,
                        confirm_process_stopped=True,
                    ),
                )
        elif action == "prepare":
            self._start(
                action,
                "Preparing the transfer…",
                lambda: transfer.prepare(self.snapshot, self.choice, self.directory),
            )
        elif action in {"original", "projection"}:
            self.runner = transfer.ProjectionRunner(self.directory)
            operation = (
                self.runner.run_original if action == "original" else self.runner.run_projection
            )

            def event(row):
                if isinstance(row, dict) and ("worker_event" in row
                                              or row.get("event") == "qualification_phase"):
                    self.progress.emit(row)

            self._start(
                action,
                "Running the original-target fit…"
                if action == "original"
                else "Transferring the approved shape…",
                lambda: operation(event_callback=event),
            )
        elif action == "review":
            from diffeoforge.desktop.reference_calibration_dialog import (
                collect_calibration_qc_pairs,
            )

            def load():
                root = transfer.original_directory(self.directory)
                snapshot = load_reference_calibration_study(root)
                candidate = snapshot.candidates[0]
                pairs = collect_calibration_qc_pairs(root, candidate)
                return snapshot, candidate, pairs

            self._start(action, "Opening the saved fit to the original…", load)
        elif action == "attach":
            self._start(
                action,
                "Verifying the reviewed fit…",
                lambda: transfer.attach_original(self.directory, self.snapshot),
            )

    def _review(self, data):
        from diffeoforge.desktop.reference_calibration_dialog import (
            CalibrationCandidateViewerDialog,
            candidate_review_payload,
        )
        from diffeoforge.reference_calibration_study import (
            record_reference_calibration_candidate_review,
        )

        snapshot, candidate, pairs = data
        root = snapshot.study_directory
        dialog = CalibrationCandidateViewerDialog(
            root, candidate, self, pairs=pairs, compact_review=True
        )
        try:
            dialog.setWindowTitle("Review transferred fit against the original specimen")
            dialog.exec()
            review = (
                candidate_review_payload(dialog, candidate.candidate_id)
                if dialog.review_recorded
                else None
            )
        finally:
            dialog.deleteLater()
        if review is None:
            self._refresh()
        else:
            self._start(
                "save",
                "Saving your review of the original-target fit…",
                lambda: record_reference_calibration_candidate_review(root, **review),
            )

    def _inspect(self):
        from diffeoforge.anatomy_retention import prepare_projection_retention
        from diffeoforge.desktop.anatomy_retention_dialog import open_retention

        open_retention(
            self, self.choice["target"], partial(prepare_projection_retention, self.directory)
        )

    def _progress(self, row):
        from diffeoforge.pilot_common_projection import BUDGET

        if self.runner is None or not self.cancel_run.isEnabled():
            return
        event = row.get("worker_event") or {}
        payload = event.get("payload") or {}
        iteration = payload.get("iteration")
        if event.get("kind") == "progress" and type(iteration) is int:
            self.progress_bar.setRange(0, BUDGET)
            self.progress_bar.setValue(iteration)
            self.progress_bar.setFormat("Iteration %v of up to %m")
            self.status.setText("Transferring the approved shape…" if self.operation == "projection"
                                else "Fitting the original specimen…")
        elif row.get("event") == "qualification_phase":
            self.progress_bar.setRange(0, 0)
            self.status.setText(row.get("message") or "Checking the saved common fit…")
        elif self.progress_bar.maximum() == 0 and payload.get("message"):
            self.status.setText(str(payload["message"]))

    def _cancel(self):
        if self.runner:
            self.runner.request_cancel()
            self.cancel_run.setEnabled(False)
            self.status.setText("Cancellation requested. Waiting for the native step to finish.")

    def _failed(self, key, message):
        self.runner = self.operation = None
        self.progress_bar.hide()
        self.cancel_run.hide()
        self.setProperty("processRecordingWaiting", False)
        self.close_button.setEnabled(True)
        self._show_action("refresh", "Recheck saved steps", message)

    def reject(self):
        if self.operation is None:
            super().reject()

    def closeEvent(self, event):  # noqa: N802
        if self.operation is not None:
            event.ignore()
        else:
            super().closeEvent(event)


def open_projection(window, snapshot, choice):
    dialog = CommonProjectionDialog(window, snapshot, choice)
    try:
        if dialog.exec() and dialog.successor is not None:
            from diffeoforge.reference_calibration_study import load_reference_calibration_study

            result = dialog.successor
            if isinstance(result, (str, Path)):
                result = load_reference_calibration_study(result)
            window._succeeded(result)
        elif dialog.stage_finished:
            window._render()
    finally:
        dialog.deleteLater()
