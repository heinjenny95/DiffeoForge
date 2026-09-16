"""One active plus one latest queued preview load, shared by non-result viewers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from diffeoforge.desktop.mesh_preview import load_mesh_preview


class _Signals(QObject):
    finished = Signal(int, object, object, str)


class _Worker(QRunnable):
    def __init__(self, token: int, key: object, operation: Callable) -> None:
        super().__init__()
        self.token, self.key, self.operation = token, key, operation
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        result, error = None, ""
        try:
            result = self.operation()
        except Exception as exception:
            error = str(exception)
        try:
            self.signals.finished.emit(self.token, self.key, result, error)
        except RuntimeError:
            pass  # Receiver was destroyed while the last parse finished.


class PreviewMeshLoader(QObject):
    activity_changed = Signal(bool)
    loaded = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._token = 0
        self._active: _Worker | None = None
        self._pending: tuple | None = None

    def cancel(self) -> None:
        self._token += 1
        self._pending = None
        self.activity_changed.emit(self._active is not None)

    def request_paths(
        self,
        key: object,
        paths: tuple[Path, ...],
        *,
        expected: tuple[str | None, ...] | None = None,
    ) -> None:
        def load() -> tuple:
            models = tuple(load_mesh_preview(path) for path in paths)
            if expected is not None:
                for model, digest in zip(models, expected, strict=True):
                    if digest is not None and model.sha256 != digest:
                        raise ValueError("Mesh changed after its approved source snapshot")
            return models

        self.request_operation(key, load)

    def request_operation(self, key: object, operation: Callable) -> None:
        self._token += 1
        self._pending = self._token, key, operation
        self._start()

    def _start(self) -> None:
        if self._active is not None or self._pending is None:
            return
        self._active = _Worker(*self._pending)
        self._pending = None
        self._active.signals.finished.connect(self._finished)
        self.activity_changed.emit(True)
        QThreadPool.globalInstance().start(self._active)

    @Slot(int, object, object, str)
    def _finished(self, token: int, key: object, value: object, error: str) -> None:
        self._active = None
        if token == self._token:
            if error:
                self.failed.emit(key, error)
            else:
                self.loaded.emit(key, value)
        self._start()
        self.activity_changed.emit(self._active is not None)
