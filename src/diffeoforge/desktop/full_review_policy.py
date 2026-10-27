"""Settled, source-bound preview decisions with optional complete geometry."""

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton


class FullGeometryReviewMixin:
    """The owner may assess the displayed preview; complete detail is optional."""

    def __init__(self, *args, **kwargs):
        self.display_started_at = time.monotonic()
        self.full_requested_at = None
        self.full_ready_at = None
        self.full_error = None
        self._relative_display_signature = None
        self._full_decision_geometry = None
        super().__init__(*args, **kwargs)
        self.canvas.original_detail.setText("Load full detail (optional, slower)")
        self.canvas.original_detail.setToolTip(
            "The preview is sufficient to approve, reject or compare this fit. "
            "Load complete original and reconstruction geometry only when needed."
        )
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(200)
        self.display_timer.timeout.connect(self._display_phase)
        self.display_timer.start()
        self.canvas.cameraChanged.connect(lambda _state: self._update_review_progress())
        saved = getattr(self, "saved_comparison", None)
        if saved:
            saved.canvas.fullResolutionReadyChanged.connect(self._update_review_progress)
            saved.toggle.toggled.connect(self._update_review_progress)
            saved.choice.currentIndexChanged.connect(self._update_review_progress)
            saved.canvas.cameraChanged.connect(lambda _state: self._update_review_progress())
        self._display_phase()

    def _relative_signature(self):
        index = self.mesh_combo.currentData()
        current = self._pairs[int(index)].pair_id if index is not None else None
        saved = getattr(self, "saved_comparison", None)
        pair = saved.choice.currentData() if saved and saved.toggle.isChecked() else None
        return current, (
            (pair.pair_id, str(pair.reconstruction_path), pair.reconstruction_sha256)
            if pair
            else None
        )

    def done(self, result):
        self.display_timer.stop()
        saved = getattr(self, "saved_comparison", None)
        if saved:
            saved.loader.cancel()
        # The caller still reads the recorded feedback after exec() returns.
        # It disposes this dialog only after copying that result.
        super().done(result)

    def _relative_ready(self):
        if not self.canvas.comparison_ready:
            return False
        saved = getattr(self, "saved_comparison", None)
        if saved and saved.toggle.isChecked() and not saved.full_comparison_ready:
            return False
        if self.fit_preferences and not self.fit_preferences.full_comparison_ready:
            return False
        return True

    def _invalidate_changed_relative_display(self):
        signature = self._relative_signature()
        previous = self._relative_display_signature
        self._relative_display_signature = signature
        if previous is not None and previous != signature and self.guided_feedback:
            group = self.guided_feedback.buttons
            group.setExclusive(False)
            for button in group.buttons():
                button.setChecked(False)
            group.setExclusive(True)
            self.guided_feedback._update()

    def _load_selected(self, index):
        self.display_started_at = time.monotonic()
        self.full_requested_at = self.full_ready_at = None
        self.full_error = None
        if hasattr(self, "display_timer"):
            self.display_timer.start()
        super()._load_selected(index)

    def _load_original_detail(self):
        self.full_error = None
        self.full_requested_at = time.monotonic()
        if hasattr(self, "display_timer"):
            self.display_timer.start()
        super()._load_original_detail()

    def _pair_loaded(self, index, models):
        super()._pair_loaded(index, models)
        self._display_phase()

    def _pair_failed(self, key, message):
        if isinstance(key, tuple) and self.canvas.original_model is not None:
            self.full_error = message
            self.canvas.original_detail.setChecked(False)
            self._update_review_progress()
            self._display_phase()
            return
        super()._pair_failed(key, message)

    def _display_phase(self):
        if not hasattr(self, "canvas"):
            return
        elapsed = time.monotonic() - self.display_started_at
        if self.canvas.comparison_ready:
            self.full_ready_at = self.full_ready_at or time.monotonic()
            original = self.canvas.original_model.triangle_count
            reconstruction = self.canvas.reconstruction_model.triangle_count
            scope = "Full detail" if self.canvas.full_resolution_ready else "Preview"
            self.status.setText(
                f"{scope} ready · original {original:,} displayed faces · reconstruction "
                f"{reconstruction:,} faces · "
                f"{self.full_ready_at - self.display_started_at:.1f}s display preparation"
            )
            if self.full_error:
                self.status.setText(
                    "Optional full detail unavailable: " + self.full_error
                    + ". Preview ready; you can still assess this fit."
                )
            if not self._relative_ready():
                self.status.setText(
                    "Current fit ready. Wait for the selected comparison preview "
                    "before relative feedback. "
                    "Hide alternatives to assess only this fit."
                )
        elif self.full_error:
            self.status.setText(
                "Optional full detail unavailable: "
                + self.full_error
                + ". The preview can still be assessed once its image is ready."
            )
        elif self.full_requested_at is not None and self._mesh_loader._active is not None:
            self.status.setText(
                f"Preparing optional full detail · {elapsed:.1f}s display time. "
                "The preview is sufficient for fit decisions."
            )
        elif self.canvas.original_model is not None and not self.canvas.original_detail.isChecked():
            self.status.setText(
                "Preparing the preview image. Full detail is optional."
            )
        else:
            self.status.setText(
                f"Rendering the selected comparison · {elapsed:.1f}s display preparation…"
            )

    def _update_review_progress(self):
        super()._update_review_progress()
        self._invalidate_changed_relative_display()
        ready = self.canvas.comparison_ready
        geometry = (id(self.canvas.original_model), id(self.canvas.reconstruction_model))
        if ready:
            self._full_decision_geometry = geometry
        if not ready:
            self.complete_button.setEnabled(False)
            self.fail_button.setEnabled(False)
            self.maybe_button.setEnabled(False)
            self.mark_region_button.setEnabled(False)
            self.specimen_decision.setEnabled(False)
            # Once this exact selected pair was presented, keep its panel layout
            # stable during rotation/repainting while disabling every decision.
            if self._full_decision_geometry != geometry:
                self.decision_panel.hide()
            self.review_gate.setText(
                "Wait for the original and reconstruction preview image "
                "to finish rendering before deciding."
            )
            self.review_gate.show()
        if self.guided_feedback:
            self.guided_feedback.set_ready(self._relative_ready() and self._valid_individual)
        self._display_phase()

    def _pair_original_presented(self):
        if self.canvas.comparison_ready:
            super()._pair_original_presented()
        else:
            self._update_review_progress()

    def _record_visual_qc_pass(self):
        if self.canvas.comparison_ready:
            super()._record_visual_qc_pass()
        else:
            self._update_review_progress()

    def _record_visual_qc_fail(self):
        if self.canvas.comparison_ready:
            super()._record_visual_qc_fail()
        else:
            self._update_review_progress()

    def _record_guided_feedback(self, decision=None):
        if self._relative_ready():
            super()._record_guided_feedback(decision)
        else:
            self._update_review_progress()

    @property
    def guided_feedback_decision(self):
        if not self._relative_ready():
            return None
        return super().guided_feedback_decision

    def _record_plan_b(self):
        if self.canvas.comparison_ready:
            super()._record_plan_b()
        else:
            self._update_review_progress()

    def _mark_region(self):
        if self.canvas.comparison_ready:
            super()._mark_region()
        else:
            self._update_review_progress()


class FullSavedComparisonMixin:
    """Load only the selected optional alternative, with matching preview sources."""

    def __init__(self, *args, **kwargs):
        self._shown_pair_id = None
        super().__init__(*args, **kwargs)
        self.retry_button = QPushButton("Retry selected comparison", self)
        self.retry_button.setObjectName("secondary")
        self.retry_button.clicked.connect(self._request)
        self.retry_button.hide()
        self.layout().addWidget(self.retry_button)
        self.loader.failed.connect(self._full_comparison_failed)

    @property
    def full_comparison_ready(self):
        if not self.toggle.isChecked():
            return True
        pair = self.choice.currentData()
        original, reconstruction = self.canvas.original_model, self.canvas.reconstruction_model
        return bool(
            pair
            and self._shown_pair_id == pair.pair_id
            and self.canvas.comparison_ready
            and original
            and reconstruction
            and original.path.resolve() == pair.original_path.resolve()
            and reconstruction.path.resolve() == pair.reconstruction_path.resolve()
            and original.sha256 == pair.original_sha256
            and reconstruction.sha256 == pair.reconstruction_sha256
        )

    def _toggle(self, visible):
        if not visible:
            self._shown_pair_id = None
            if hasattr(self, "retry_button"):
                self.retry_button.hide()
        super()._toggle(visible)

    def _request(self, *_args):
        self._shown_pair_id = None
        self.canvas.clear()  # Old geometry must not stand below a new selection label.
        if hasattr(self, "retry_button"):
            self.retry_button.hide()
        if not self.toggle.isChecked() or self.choice.currentData() is None:
            return
        pair = self.choice.currentData()
        self.status.setText(
            "Preparing the selected comparison preview… Relative feedback waits for its image."
        )
        self.loader.request_paths(
            pair.pair_id,
            (pair.original_path, pair.reconstruction_path),
            expected=(pair.original_sha256, pair.reconstruction_sha256),
            pilot_cache=self.cache_directory,
        )

    def _loaded(self, key, models):
        pair = self.choice.currentData()
        if not self.toggle.isChecked() or not pair or key != pair.pair_id:
            return
        if any(
            model.path.resolve() != path.resolve() or model.sha256 != digest
            for model, path, digest in zip(
                models,
                (pair.original_path, pair.reconstruction_path),
                (pair.original_sha256, pair.reconstruction_sha256),
                strict=True,
            )
        ):
            self._full_comparison_failed(key, "Displayed models do not match the selected source")
            return
        super()._loaded(key, models)
        if self.canvas.reconstruction_model is None:
            return
        self._shown_pair_id = pair.pair_id
        self.status.setText(
            "Selected comparison loaded; relative feedback waits for its image."
        )

    def _full_comparison_failed(self, key, message):
        pair = self.choice.currentData()
        if not self.toggle.isChecked() or not pair or key != pair.pair_id:
            return
        self._shown_pair_id = None
        self.canvas.clear()
        self.retry_button.show()
        self.status.setText(
            "Selected comparison unavailable: "
            + message
            + ". Retry this comparison or hide alternatives to assess the current fit."
        )


class FullFitPreferenceMixin:
    """The legacy ranking panel also permits matching settled previews."""

    @property
    def full_comparison_ready(self):
        if not self._ready or not self.current_canvas.comparison_ready:
            return False
        reference = self._comparison.get("reference") if self._comparison else None
        return not reference or bool(
            self.reference_canvas.comparison_ready
            and self.show_comparison.isChecked()
            and self.reference_combo.currentData() == reference
        )

    def _update_actions(self):
        super()._update_actions()
        if hasattr(self, "feedback_buttons") and not self.full_comparison_ready:
            for button in self.feedback_buttons.values():
                button.setEnabled(False)
            self.start_button.setEnabled(False)

    @property
    def selection_ready(self):
        return self.full_comparison_ready and super().selection_ready
