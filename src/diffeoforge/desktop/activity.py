"""Window-scoped, signal-bound activity feedback; never invents progress or ETA."""

from __future__ import annotations

import weakref
from itertools import count

from PySide6.QtCore import QObject, Qt, QThreadPool, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget
from shiboken6 import isValid

_LABELS = {
    "_ProjectWorker": "Preparing project",
    "_ReviewWorker": "Checking configuration and workload",
    "_InputPreflightWorker": "Checking mesh inputs",
    "_TemplatePreviewWorker": "Loading template",
    "_ProcrustesPreviewWorker": "Computing alignment preview",
    "_ProcrustesVisualWorker": "Loading alignment preview",
    "_ReferenceParameterWorker": "Measuring parameter starting values",
    "_ReferenceReadinessWorker": "Checking Deformetrica installation",
    "_ReferencePreparationStatusWorker": "Verifying prepared reference run",
    "_SavedReferencePreparationStatusVerificationWorker": "Verifying saved preparation",
    "_ResultReviewWorker": "Verifying atlas results",
    "_ScientificReportWorker": "Creating scientific report",
    "_PublicationBundleWorker": "Creating reproducibility bundle",
    "_PCAMetadataWorker": "Checking PCA metadata",
    "_ReferencePCADeformationWorker": "Computing PC deformation meshes",
    "_ReferenceShapeSpaceComparisonWorker": "Comparing shape-space methods",
    "_AbandonedReferenceRecoveryWorker": "Checking interrupted-run recovery",
    "_ArtifactWorker": "Verifying result file",
    "_AtlasWorker": "Running atlas",
    "_RemoteAtlasWorker": "Monitoring remote atlas",
    "_RemoteAtlasDeletionWorker": "Removing approved remote copy",
    "_ReferenceAtlasWorker": "Running Deformetrica atlas",
    "_CalibrationStageWorker": "Running pilot calibration",
    "_PreparationWorker": "Preparing Validation Lab",
    "_ValidationWorker": "Running Validation Lab",
}


class ActivityIndicator(QWidget):
    """Own only this window's cursor; other windows and override stacks are untouched."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self._owner = weakref.ref(owner)
        self.tasks: dict[object, str] = {}
        self._previous_cursor = None
        self._had_cursor = False
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.setTextVisible(False)
        self.spinner.setFixedSize(64, 12)
        self.spinner.setAccessibleName("Work in progress; duration unknown")
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.spinner)
        row.addWidget(self.label, 1)
        self.hide()

    def bind_loader(self, loader: QObject, label: str) -> None:
        binding = _LoaderBinding(self, loader, label)
        loader.activity_changed.connect(binding.update)

    def set_task(self, key: object, label: str | None) -> None:
        owner = self._owner()
        if owner is None or not isValid(owner):
            return
        if label is None:
            self.tasks.pop(key, None)
        else:
            self.tasks[key] = label
        active = bool(self.tasks)
        if active and self._previous_cursor is None:
            self._had_cursor = owner.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
            self._previous_cursor = owner.cursor()
            owner.setCursor(Qt.CursorShape.BusyCursor)
        elif not active and self._previous_cursor is not None:
            if self._had_cursor:
                owner.setCursor(self._previous_cursor)
            else:
                owner.unsetCursor()
            self._previous_cursor = None
        labels = list(self.tasks.values())
        suffix = f" (+{len(labels) - 1} other task(s))" if len(labels) > 1 else ""
        self.label.setText((labels[0] + "…" + suffix) if labels else "")
        self.setVisible(active)


class _Ticket(QObject):
    def __init__(self, pool: ActivityPool, key: int, worker: object) -> None:
        super().__init__(pool.indicator)
        self._pool, self.key = weakref.ref(pool), key
        # Terminal signals are queued to the GUI. Keep the Python wrapper alive
        # until that delivery, including while a completion slot starts its successor.
        self.worker: object | None = worker

    @Slot(object)
    def progress(self, value: object) -> None:
        pool = self._pool()
        if pool is None or self.key not in pool._tickets:
            return
        if isinstance(value, tuple) and len(value) == 3:
            completed, total, message = value
            if isinstance(completed, int) and isinstance(total, int) and 0 <= completed <= total:
                count = f"{completed} of {total}: " if total else ""
                pool.indicator.set_task(self.key, count + str(message))

    @Slot()
    def finish(self) -> None:
        pool = self._pool()
        if pool is not None and pool._tickets.get(self.key) is self:
            pool._tickets.pop(self.key)
            pool.indicator.set_task(self.key, None)
        self.worker = None
        self.deleteLater()


class _LoaderBinding(QObject):
    def __init__(self, indicator: ActivityIndicator, loader: QObject, label: str) -> None:
        super().__init__(indicator)
        self._indicator = weakref.ref(indicator)
        self.key, self.label = ("loader", id(loader)), label

    @Slot(bool)
    def update(self, active: bool) -> None:
        indicator = self._indicator()
        if indicator is not None and isValid(indicator):
            indicator.set_task(self.key, self.label if active else None)


class ActivityPool:
    """Track the existing workers without changing their execution or cancellation."""

    def __init__(self, owner: QWidget, *, pool=None) -> None:
        self.indicator = ActivityIndicator(owner)
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._tickets: dict[int, _Ticket] = {}
        self._keys = count()

    def start(self, worker) -> None:
        if any(ticket.worker is worker for ticket in self._tickets.values()):
            return  # The same runnable must never be queued twice.
        # Object addresses can be reused before an older queued finish arrives.
        # A monotonically assigned ticket cannot suppress or clear another task.
        key = next(self._keys)
        ticket = _Ticket(self, key, worker)
        worker.signals.succeeded.connect(ticket.finish)
        worker.signals.failed.connect(ticket.finish)
        if hasattr(worker.signals, "progress"):
            worker.signals.progress.connect(ticket.progress)
        self._tickets[key] = ticket
        self.indicator.set_task(key, _LABELS.get(type(worker).__name__, "Working"))
        try:
            self._pool.start(worker)
        except Exception:
            ticket.finish()
            raise
