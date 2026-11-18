"""View a bound pair of saved pilot fits with the same original and camera."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.reference_calibration_dialog import (
    _FullscreenPilotDialog,
    collect_calibration_qc_pairs,
)

_PREPARING = "Preparing both saved overlays…"
_OPEN = "Saved-fit comparison open. Close it to return to the pilot."


@dataclass
class _ComparisonRequest:
    origin: Path
    direction: dict
    previous_status: str
    loader_token: int | None = None


def _request_current(window, request, *, check_generation=True):
    return (getattr(window, "_guided_comparison_request", None) is request
            and not window._view_closed and not window._review_saving
            and window.study_directory == request.origin and not window._worker
            and (not check_generation or request.loader_token is None
                 or window._viewer_preparation.is_current_request(request.loader_token)))


def _finish_request(window, key, *, error=None, cancelled=False):
    request = key[3] if len(key) > 3 else None
    if request is None or getattr(window, "_guided_comparison_request", None) is not request:
        return
    current = _request_current(window, request, check_generation=not cancelled)
    window._guided_comparison_request = None
    if not current:
        return
    if error is not None:
        message = str(error).strip() or type(error).__name__
        window.status.setText("Comparison unavailable: " + message)
    elif window.status.text() in {_PREPARING, _OPEN}:
        window.status.setText(request.previous_status or "Return to the saved fit's next step.")


def preparation_failed(window, key, message):
    """Discard stale-origin failures and release the explicit comparison request."""
    _finish_request(window, key, error=message)


def preparation_cancelled(window):
    request = getattr(window, "_guided_comparison_request", None)
    if request is not None:
        _finish_request(window, ("guided-fit-direction", request.origin,
                                 request.direction, request), cancelled=True)


def preparation_replaced(window):
    request = getattr(window, "_guided_comparison_request", None)
    if (request is not None and request.loader_token is not None
            and not window._viewer_preparation.is_current_request(request.loader_token)):
        preparation_cancelled(window)


def _prepare(origin, direction):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.guided_density import controls_for
    from diffeoforge.guided_feedback import verify_reference
    from diffeoforge.reference_guided_pilot import record

    with study.calibration_verification_scope():
        active = study.load_reference_calibration_study(origin)
        info = record(active)
        target = direction["target"]
        if not info or info["target"] != target:
            raise ValueError("The current pilot form changed. Reopen the comparison.")
        allowed = {str(active.study_directory), *(row["directory"] for row in info["history"])}
        active_inputs = study._verify_manifest(active.study_directory)["inputs"]
        subject = next((row for row in active_inputs["subjects"]
                        if row["filename"] == target), None)
        if subject is None:
            raise ValueError(f"The current pilot inputs do not contain {target}. "
                             "Reopen this specimen's saved result.")
        source = (subject["sha256"], active_inputs["template"]["sha256"])
        bindings = []
        for name in ("current", "alternative"):
            reference = direction[name]
            if reference["directory"] not in allowed or reference["target"] != target:
                raise ValueError("The comparison fits do not belong to this pilot form.")
            parent = verify_reference(reference)
            saved = record(parent)
            if (not saved or Path(saved["origin"]).resolve() != Path(info["origin"]).resolve()
                    or parent.plan.pilot_subject_count != 1):
                raise ValueError("The comparison requires two saved single-form results.")
            candidate = next((c for c in parent.candidates
                              if c.candidate_id == reference["candidate_id"]), None)
            if candidate is None:
                raise ValueError(f"Saved {reference['method']} fit "
                                 f"{reference['candidate_id']} is missing for {target}. "
                                 "Reopen the saved result before comparing it.")
            manifest = study._verify_manifest(parent.study_directory)
            pair = next((p for p in collect_calibration_qc_pairs(parent.study_directory, candidate)
                         if p.required and p.original_path.name == target), None)
            if pair is None:
                raise ValueError(f"Saved {reference['method']} fit "
                                 f"{reference['candidate_id']} has no original/reconstruction "
                                 f"pair for {target}. Reopen its saved export for inspection.")
            template_sha = manifest["inputs"]["template"]["sha256"]
            if (not all(source) or (pair.original_sha256, template_sha) != source
                    or not pair.reconstruction_sha256):
                raise ValueError("The compared fits must share the exact original and template.")
            count = controls_for(parent.attachment_comparison, candidate.candidate_id)["count"]
            if count != direction[f"{name}_cp"]:
                raise ValueError("The saved control-point count changed. Reopen the comparison.")
            headline = (f"{reference['method'].title()} · Test {saved['screen_trials_spent']} "
                        f"· {count:,} CP")
            bindings.append((pair, headline))
        left, right = bindings
        return (left[0], right[0]), (left[1], right[1])


def open_comparison(window, direction):
    if window._worker or window._view_loading or window._view_closed or window._review_saving:
        return
    origin = window.study_directory
    previous = getattr(window, "_guided_comparison_request", None)
    if (previous is not None and previous.origin == origin and previous.direction == direction
            and _request_current(window, previous)):
        return  # Repeated clicks must not queue another full evidence verification.
    previous_status = (previous.previous_status if previous is not None
                       and previous.origin == origin and window.status.text() == _PREPARING
                       else window.status.text())
    if previous_status in {_PREPARING, _OPEN}:
        previous_status = "Saved-fit comparison closed. Return to the next pilot step."
    request = _ComparisonRequest(origin, deepcopy(direction), previous_status)
    window._guided_comparison_request = request
    window.status.setText(_PREPARING)
    key = ("guided-fit-direction", origin, request.direction, request)
    try:
        request.loader_token = window._viewer_preparation.request_operation(
            key, lambda: _prepare(origin, request.direction),
        )
    except Exception as error:
        _finish_request(window, key, error=error)


def _markers(original_bounds, regions):
    low = np.asarray(original_bounds[::2])
    span = np.asarray(original_bounds[1::2]) - low
    return {
        f"Area {index}": tuple(low + (np.asarray(row["cell"]) + 0.5) * span / 4)
        for index, row in enumerate(regions, 1)
    }


class _ComparisonDialog(_FullscreenPilotDialog):
    """Open two settled overlays before handing an explicit choice to the pilot."""

    def __init__(self, window, origin, direction, prepared):
        super().__init__(window)
        (left, right), labels = prepared
        self.paths = (left.original_path, left.reconstruction_path, right.reconstruction_path)
        self.hashes = (
            left.original_sha256, left.reconstruction_sha256, right.reconstruction_sha256,
        )
        self.cache = origin / "display-cache"
        self._references = direction["current"], direction["alternative"]
        self._regions = direction["regions"]
        self._markers = ()
        self._overview = None
        self._loaded_detail = None
        self.working_view = None
        self.setWindowTitle("Compare saved pilot fits")
        self.resize(1180, 730)
        self.setMinimumSize(620, 430)
        self.setProperty("processRecordingPilotReview", True)
        layout = QVBoxLayout(self)
        title = QLabel(direction["target"])
        title.setObjectName("title")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        hint = QLabel("Orange lines show the same original in both views. "
                      "Blue shows each saved fit. Rotate either view to compare the same area.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        views = QHBoxLayout()
        self.canvases = tuple(CalibrationComparisonCanvas3D(
            self, show_inspection_hints=False) for _ in labels)
        for index, (heading, canvas) in enumerate(zip(labels, self.canvases, strict=True)):
            panel = QVBoxLayout()
            metric = direction["alternative_p95" if index else "current_p95"]
            label = QLabel(f"{heading} · P95 {metric:.2f}%")
            label.setWordWrap(True)
            panel.addWidget(label)
            canvas.setMinimumHeight(230)
            canvas.original_detail.hide()
            panel.addWidget(canvas, 1)
            views.addLayout(panel, 1)
        layout.addLayout(views, 1)
        self.canvases[0].cameraChanged.connect(self.canvases[1].set_linked_camera)
        self.canvases[1].cameraChanged.connect(self.canvases[0].set_linked_camera)

        if self._regions:
            areas = "  ·  ".join(
                f"Area {index}: {row['current_p95']:.1f}% → {row['alternative_p95']:.1f}%"
                for index, row in enumerate(self._regions, 1))
            caption = QLabel(areas + "\nNumbered areas show approximate locations from "
                             "repeated measurements. Check their anatomy in both views.")
            caption.setWordWrap(True)
            layout.addWidget(caption)
            if direction.get("tradeoff"):
                question = QLabel(
                    "Which area contains the structure your study needs to preserve?"
                )
                question.setWordWrap(True)
                layout.addWidget(question)
                navigation = QHBoxLayout()
                areas = [f"Area {i}" for i in range(1, len(self._regions) + 1)]
                for name in ("Whole shape", *areas):
                    button = QPushButton(name)
                    button.clicked.connect(lambda _checked=False, key=name: self._focus(key))
                    navigation.addWidget(button)
                navigation.addStretch()
                layout.addLayout(navigation)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(self.full_screen_button)
        self.detail = QCheckBox("Load full detail (optional, slower)")
        actions.addWidget(self.detail)
        actions.addStretch()
        close = QPushButton("Close comparison")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.fit_actions = QHBoxLayout()
        self.keep_left = QPushButton(f"Work from {labels[0]}…")
        self.keep_left.setEnabled(False)
        self.keep_left.clicked.connect(lambda: self._choose_fit(0))
        self.fit_actions.addWidget(self.keep_left, 1)
        self.work = QPushButton(f"Work from {labels[1]}…")
        # A trade-off (or an unranked pair) does not justify visually favouring
        # the right-hand fit. Keep both named choices available after inspection.
        if direction.get("metric_preference") == "alternative" and not direction.get("tradeoff"):
            self.work.setObjectName("primary")
            self.work.setToolTip("Lower sampled surface distances; your visual review "
                                 "still determines anatomical suitability.")
        self.work.clicked.connect(lambda: self._choose_fit(1))
        self.work.setEnabled(False)
        self.fit_actions.addWidget(self.work, 1)
        layout.addLayout(self.fit_actions)
        self._arrange_actions()

        self.loader = PreviewMeshLoader(self)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.loader.activity_changed.connect(
            lambda busy: self.setProperty("processRecordingWaiting", busy))
        self.finished.connect(self.loader.cancel)
        self.detail.toggled.connect(self._request)
        for canvas in self.canvases:
            canvas.fullResolutionReadyChanged.connect(self._update_actions)
        self._request(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "fit_actions"):
            self._arrange_actions()

    def _arrange_actions(self):
        required = self.keep_left.sizeHint().width() + self.work.sizeHint().width() + 50
        self.fit_actions.setDirection(
            QBoxLayout.Direction.TopToBottom if self.width() < max(900, required)
            else QBoxLayout.Direction.LeftToRight
        )

    def _request(self, detail):
        self._loaded_detail = None
        self._update_actions()
        self.status.setText("Loading both saved overlays…")
        self.loader.request_paths(
            detail, self.paths, expected=self.hashes, pilot_cache=None if detail else self.cache,
        )

    def _loaded(self, detail, models):
        if detail != self.detail.isChecked():
            return
        if any(model.path.resolve() != path.resolve() or model.sha256 != digest
               for model, path, digest in zip(models, self.paths, self.hashes, strict=True)):
            self._failed(detail, "Displayed meshes do not match the saved fits.")
            return
        original, left, right = models
        bounds = np.asarray([model.bounds for model in models])
        low, high = bounds[:, ::2].min(axis=0), bounds[:, 1::2].max(axis=0)
        markers = _markers(original.bounds, self._regions)
        self._markers = tuple(markers.items())
        self._overview = ((low + high) / 2, float(max(high - low)))
        for canvas, reconstruction in zip(self.canvases, (left, right), strict=True):
            canvas.set_models(original, reconstruction)
            canvas.set_comparison_extent(*self._overview)
            canvas.set_inspection_markers(markers)
            if detail:
                canvas.original_detail.setChecked(True)
        self._loaded_detail = detail
        self.status.setText("P95 is a sampled surface distance as a percentage of the original "
                            "diagonal. Your visual review determines suitability.")
        self._update_actions()

    def _focus(self, area):
        if self._overview is None or self._loaded_detail != self.detail.isChecked():
            return
        center, scale = self._overview
        if area != "Whole shape":
            center = np.asarray(dict(self._markers)[area])
            scale *= 0.55
        state = self.canvases[0].camera_state()
        centered = (*state[:2], 1.0, (0.0, 0.0), False, *state[5:])
        for canvas in self.canvases:
            canvas.set_comparison_extent(center, scale)
            canvas.set_linked_camera(centered)

    def _failed(self, detail, message):
        if detail == self.detail.isChecked():
            self.status.setText("Comparison unavailable. " + message)

    def _update_actions(self):
        ready = (self._loaded_detail == self.detail.isChecked()
                 and all(canvas.comparison_ready for canvas in self.canvases))
        self.work.setEnabled(ready)
        self.keep_left.setEnabled(ready)

    def _choose_fit(self, position):
        self._update_actions()
        if self.work.isEnabled():
            camera = self.canvases[position].camera_state()
            self.working_view = dict(
                reference=self._references[position],
                hashes=(self.hashes[0], self.hashes[position + 1]),
                camera=(*camera[:4], False, *camera[5:]),
                markers=self._markers,
            )
            self.accept()


def show_comparison(window, direction, prepared, *, request_key=None):
    origin = window.study_directory
    if request_key is not None and not _request_current(window, request_key[3]):
        _finish_request(window, request_key)
        return
    dialog = None
    chosen = None
    choice_current = False
    try:
        dialog = _ComparisonDialog(window, origin, direction, prepared)
        if request_key is not None:
            window.status.setText(_OPEN)
        chosen = dialog.working_view if dialog.exec() == QDialog.DialogCode.Accepted else None
        choice_current = request_key is None or _request_current(window, request_key[3])
    except Exception as error:
        if request_key is not None:
            _finish_request(window, request_key, error=error)
        elif window.study_directory == origin and not window._worker:
            window.status.setText("Comparison unavailable: " + (
                str(error).strip() or type(error).__name__))
    finally:
        if dialog is not None:
            dialog.deleteLater()
        if request_key is not None:
            _finish_request(window, request_key)
    if (chosen and choice_current and window.study_directory == origin and not window._worker
            and not window._view_closed and not window._review_saving):
        window._open_guided_working_fit(
            direction["identifier"], chosen["reference"], view_hint=chosen,
        )
