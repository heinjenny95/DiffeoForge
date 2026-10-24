"""Explicit multiple-specimen selection and asynchronous correction preparation."""

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge import landmark_correction as correction


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class CorrectionTask(QRunnable):
    def __init__(self, function, *args):
        super().__init__()
        self.function, self.args = function, args
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            result = self.function(*self.args)
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(result)


class LandmarkCorrectionPicker(QDialog):
    def __init__(self, source, mesh_paths, project, parent=None):
        super().__init__(parent)
        self.source, self.paths, self.project = source, mesh_paths, project
        self.session, self._worker = None, None
        self.setWindowTitle("Correct/change existing landmarks")
        self.resize(740, 620)
        layout = QVBoxLayout(self)
        text = QLabel("Choose the specimens to correct. Existing points will be loaded; "
                      "all other specimens keep their landmarks.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a specimen…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAccessibleName("Specimens to correct")
        for p in mesh_paths:
            item = QListWidgetItem(p.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(self._update)
        layout.addWidget(self.list, 1)
        selection = QHBoxLayout()
        for label, checked in (("Select all", True), ("Clear selection", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, value=checked: self._select(value))
            selection.addWidget(button)
        layout.addLayout(selection)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.edit = QPushButton("Edit selected specimens")
        self.edit.setObjectName("primary")
        self.edit.clicked.connect(self._prepare)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.edit, 1)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self._update()

    @property
    def selected(self):
        return tuple(self.list.item(i).text() for i in range(self.list.count())
                     if self.list.item(i).checkState() == Qt.CheckState.Checked)

    def _filter(self, text):
        for i in range(self.list.count()):
            self.list.item(i).setHidden(text.casefold() not in self.list.item(i).text().casefold())

    def _select(self, checked):
        if self._worker:
            return
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _update(self, *_):
        if self._worker:
            return
        self.status.setText(f"{len(self.selected)} of {self.list.count()} specimens selected.")
        self.edit.setEnabled(bool(self.selected))

    def _prepare(self):
        if self._worker or not self.selected:
            return
        self._worker = CorrectionTask(correction.prepare, self.source, self.paths,
                                      self.selected, self.project)
        self._worker.signals.succeeded.connect(self._prepared)
        self._worker.signals.failed.connect(self._failed)
        self.edit.setEnabled(False)
        self.list.setEnabled(False)
        self.status.setText("Loading saved coordinates and checking selected source meshes…")
        QThreadPool.globalInstance().start(self._worker)

    @Slot(object)
    def _prepared(self, session):
        self._worker = None
        self.session = session
        self.accept()

    @Slot(str)
    def _failed(self, message):
        self._worker = None
        self.list.setEnabled(True)
        self.edit.setEnabled(bool(self.selected))
        self.status.setText(message)

    def reject(self):
        if self._worker:
            self.status.setText("Please wait for the source check to finish before closing.")
            return
        super().reject()
