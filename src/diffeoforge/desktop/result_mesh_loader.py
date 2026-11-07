"""Serial, latest-selection-only background loader for verified result geometry."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
from diffeoforge.desktop.result_review import (
    ModernResultReview,
    ModernResultReviewError,
    verify_result_artifact,
)


class _LoadSignals(QObject):
    finished = Signal(object, object, object, str)


class _LoadWorker(QRunnable):
    def __init__(self, request: tuple, cache: OrderedDict) -> None:
        super().__init__()
        self.request = request
        self.cache = cache
        self.signals = _LoadSignals()

    @Slot()
    def run(self) -> None:
        token, review, key = self.request
        try:
            if key.startswith("registration-qc:"):
                item = review.registration_qc_item(key.split(":", 1)[1])
                keys = (item.original_artifact_key, item.reconstruction_artifact_key)
            else:
                keys = (key,)
            models = []
            for artifact_key in keys:
                # Cache hits do not bypass fresh manifest, path, size or hash checks.
                path = verify_result_artifact(review, artifact_key)
                expected = review.artifact(artifact_key).sha256
                identity = (path, expected)
                model = self.cache.get(identity)
                if model is None:
                    model = load_mesh_preview(path)
                if model.sha256 != expected:
                    raise ModernResultReviewError(
                        "Loaded mesh differs from verified artifact bytes"
                    )
                self.cache[identity] = model
                self.cache.move_to_end(identity)
                # Bounded by both model count and aggregate faces (one oversize mesh allowed).
                while len(self.cache) > 1 and (
                    len(self.cache) > 4
                    or sum(m.triangle_count for m in self.cache.values()) > 1_000_000
                ):
                    self.cache.popitem(last=False)
                models.append(model)
            result, error_text = (key, tuple(models)), ""
        except Exception as error:
            self.cache.clear()
            result, error_text = (key, ()), str(error)
        try:
            self.signals.finished.emit(token, review, result, error_text)
        except RuntimeError:
            # Application teardown can destroy the receiver while parsing finishes.
            pass


class ResultMeshLoader(QObject):
    """Keep the GUI responsive and discard results belonging to an old selection."""

    loaded = Signal(object, str, object)
    failed = Signal(object, str, str)
    activity_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._token = 0
        self._active: _LoadWorker | None = None
        self._pending: tuple | None = None
        self._cache: OrderedDict[tuple, MeshPreviewModel] = OrderedDict()

    def cancel(self) -> None:
        self._token += 1
        self._pending = None

    def request(self, review: ModernResultReview, key: str) -> None:
        self._token += 1
        self._pending = (self._token, review, key)
        self._start_pending()

    def _start_pending(self) -> None:
        if self._active is not None or self._pending is None:
            return
        self._active = _LoadWorker(self._pending, self._cache)
        self._pending = None
        self._active.signals.finished.connect(self._finished)
        self.activity_changed.emit(True)
        QThreadPool.globalInstance().start(self._active)

    @Slot(object, object, object, str)
    def _finished(self, token: int, review: ModernResultReview, result: tuple, error: str) -> None:
        self._active = None
        key, models = result
        if token == self._token:
            if error:
                self.failed.emit(review, key, error)
            else:
                self.loaded.emit(review, key, models)
        self._start_pending()
        self.activity_changed.emit(self._active is not None)
