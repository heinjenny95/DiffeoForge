"""Explicit prospective mesh-resolution study; never starts a numerical backend."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from diffeoforge.mesh_resolution_study import assess_study, freeze_study, load_study

_WORK = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh-resolution-study")


class MeshResolutionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scientific mesh resolution")
        self.resize(980, 600)
        self.root = self.plan = self.future = self.report = None
        self.assignments = {}
        self.messages, self.cancelled = SimpleQueue(), Event()
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Freeze approved mesh levels and tolerances before running their atlases. "
            "Then assign completed results and compare. Original meshes stay unchanged."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.create = QPushButton("Create from study plan…")
        self.create.clicked.connect(self._create)
        self.open = QPushButton("Open saved study…")
        self.open.clicked.connect(self._open)
        row.addWidget(self.create)
        row.addWidget(self.open)
        layout.addLayout(row)
        self.status = QLabel("Choose a plan JSON or open a frozen study.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Level", "Median faces", "Completed run", ""))
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.compare = QPushButton("Assess and create report")
        self.compare.clicked.connect(self._assess)
        self.compare.setEnabled(False)
        self.show_report = QPushButton("Open report")
        self.show_report.clicked.connect(self._show_report)
        self.show_report.setEnabled(False)
        self.cancel = QPushButton("Cancel verification")
        self.cancel.clicked.connect(self._cancel)
        self.cancel.hide()
        actions.addWidget(self.compare)
        actions.addWidget(self.show_report)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._poll)

    def _start(self, function, text, action):
        self.cancelled.clear()
        self.action = action
        self.status.setText(text)
        self.create.setEnabled(False)
        self.open.setEnabled(False)
        self.compare.setEnabled(False)
        self.table.setEnabled(False)
        self.cancel.setVisible(action == "report")
        self.cancel.setEnabled(True)
        self.future = _WORK.submit(function)
        self.timer.start()

    def _create(self):
        spec, _ = QFileDialog.getOpenFileName(self, "Approved study plan", "", "JSON (*.json)")
        if not spec:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "New study folder", str(Path(spec).parent / "mesh-resolution-study"), "Folder (*)"
        )
        if target:

            def create():
                root = freeze_study(spec, target)
                return root, load_study(root)

            self._start(create, "Freezing the approved design…", "study")

    def _open(self):
        path = QFileDialog.getExistingDirectory(self, "Frozen mesh-resolution study")
        if path:
            self._start(
                lambda: (Path(path), load_study(path)), "Verifying the saved study…", "study"
            )

    def _render(self):
        self.table.setRowCount(len(self.plan["levels"]))
        for index, level in enumerate(self.plan["levels"]):
            key = level["id"]
            label = QTableWidgetItem(key)
            label.setToolTip("Run configuration: " + level["run_config"]["path"])
            self.table.setItem(index, 0, label)
            self.table.setItem(index, 1, QTableWidgetItem(f"{level['median_subject_faces']:g}"))
            selected = self.assignments.get(key)
            item = QTableWidgetItem(Path(selected).name if selected else "Not assigned")
            item.setToolTip(str(selected or ""))
            self.table.setItem(index, 2, item)
            choose = QPushButton("Choose run…")
            choose.clicked.connect(lambda _checked=False, name=key: self._assign(name))
            self.table.setCellWidget(index, 3, choose)
        self.table.resizeColumnsToContents()
        self.compare.setEnabled(len(self.assignments) == len(self.plan["levels"]))

    def _assign(self, key):
        path = QFileDialog.getExistingDirectory(self, f"Completed run for {key}")
        if path:
            self.assignments[key] = path
            self.status.setText(
                "Run selected. The report checks its exact level and design binding."
            )
            self._render()

    def _progress(self, text):
        if self.cancelled.is_set():
            raise InterruptedError(
                "Assessment cancelled; existing study and results were preserved"
            )
        self.messages.put(text)

    def _cancel(self):
        self.cancelled.set()
        self.cancel.setEnabled(False)
        self.status.setText("Cancellation requested. Finishing the current verification…")

    def _assess(self):
        root, assignments = self.root, dict(self.assignments)
        target = root / "assessments" / ("assessment-" + uuid4().hex[:12])
        self._start(
            lambda: assess_study(root, assignments, target, progress=self._progress),
            "Verifying assigned runs…",
            "report",
        )

    def _poll(self):
        try:
            while True:
                text = self.messages.get_nowait()
                if not self.cancelled.is_set():
                    self.status.setText(text)
        except Empty:
            pass
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        self.create.setEnabled(True)
        self.open.setEnabled(True)
        self.table.setEnabled(True)
        self.cancel.hide()
        try:
            result = future.result()
            if self.action == "study":
                self.root, self.plan = result
                self.assignments = {}
                self.status.setText(
                    "Design frozen. Use the configs in the levels folder for explicit atlas runs, "
                    "then assign each result here."
                )
                self._render()
            else:
                self.report = result / "report.html"
                self.show_report.setEnabled(True)
                self.status.setText(
                    "Assessment saved. Open the report for the result and next actions."
                )
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
            self.status.setText(str(error))
        if self.plan is not None:
            self.compare.setEnabled(len(self.assignments) == len(self.plan["levels"]))

    def _show_report(self):
        if self.report is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report)))

    def closeEvent(self, event):  # noqa: N802
        if self.future is not None:
            self._cancel()
            event.ignore()
            return
        super().closeEvent(event)
