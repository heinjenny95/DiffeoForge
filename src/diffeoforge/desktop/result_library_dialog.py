"""A searchable result chooser; directory scanning never runs on the GUI thread."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from shiboken6 import isValid

from diffeoforge.desktop.completed_results import CompletedResultRun
from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.desktop.recent_projects import load_recent_projects
from diffeoforge.desktop.result_library import (
    ResultLibraryEntry,
    ResultLibraryScan,
    entry_name,
    load_library_preferences,
    save_library_preference,
    scan_result_library,
)


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _ScanWorker(QRunnable):
    def __init__(self, roots: tuple[Path, ...]) -> None:
        super().__init__()
        self.roots = roots
        self.cancelled = Event()
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            result = scan_result_library(self.roots, self.cancelled)
        except Exception as error:
            if not self.cancelled.is_set() and isValid(self.signals):
                self.signals.failed.emit(f"{type(error).__name__}: {error}")
            return
        if not self.cancelled.is_set() and isValid(self.signals):
            self.signals.succeeded.emit(result)


class ResultLibraryDialog(QDialog):
    def __init__(self, initial: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open results")
        self.resize(960, 570)
        self.selected_result: CompletedResultRun | None = None
        self._preferences = load_library_preferences()
        self._roots = [Path(p) for p in self._preferences["roots"]]
        self._roots.extend(Path(p) for p in self._preferences["opened"])
        self._roots.extend(p.project_directory for p in load_recent_projects())
        if initial is not None:
            self._roots.insert(0, initial)
        self._worker: _ScanWorker | None = None
        self._started = False
        self._closed = False
        self._scan = ResultLibraryScan((), 0, False, ())
        self._visible: list[ResultLibraryEntry] = []
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects, dates or run IDs")
        self.search.setAccessibleName("Search completed results")
        self.search.textChanged.connect(self._filter)
        self.show_pilots = QCheckBox("Include trial fits")
        self.show_pilots.toggled.connect(self._filter)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.show_pilots)
        layout.addLayout(controls)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Project / saved name", "Specimens", "Date", "Type"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._open())
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.location = QLabel("Select a result to see its location.")
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.location_details = InfoDisclosure("Location and verification", self.location)
        layout.addWidget(self.location_details)
        actions = QHBoxLayout()
        self.add_folder = QPushButton("Add project folder…")
        self.add_folder.clicked.connect(self._add_folder)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.rename_button = QPushButton("Name result…")
        self.rename_button.clicked.connect(self._rename)
        actions.addWidget(self.add_folder)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.rename_button)
        actions.addStretch()
        self.open_button = QPushButton("Open selected result")
        self.open_button.clicked.connect(self._open)
        self.open_button.setDefault(True)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        actions.addWidget(self.open_button)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._selection_changed()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self.refresh)

    @Slot()
    def refresh(self) -> None:
        if self._worker is not None or self._closed:
            return
        self._preferences = load_library_preferences()
        self.status.setText("Finding completed results…")
        self.refresh_button.setEnabled(False)
        self.add_folder.setEnabled(False)
        worker = _ScanWorker(tuple(dict.fromkeys(self._roots)))
        self._worker = worker
        self._selection_changed()
        worker.signals.succeeded.connect(self._found)
        worker.signals.failed.connect(self._failed)
        try:
            QThreadPool.globalInstance().start(worker)
        except Exception as error:
            self._failed(str(error))

    @Slot(object)
    def _found(self, scan: ResultLibraryScan) -> None:
        self._worker = None
        self._scan = scan
        self.refresh_button.setEnabled(True)
        self.add_folder.setEnabled(True)
        self._filter()

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._worker = None
        self.status.setText("Search failed. Try a more specific project folder.")
        self.status.setToolTip(message)
        self.refresh_button.setEnabled(True)
        self.add_folder.setEnabled(True)
        self._selection_changed()

    @Slot()
    def _filter(self) -> None:
        previous = self._selected()
        terms = self.search.text().casefold().split()
        self._visible = [
            e
            for e in self._scan.entries
            if (self.show_pilots.isChecked() or not e.pilot)
            and all(
                term
                in (
                    f"{entry_name(e, self._preferences)} {e.project_name} "
                    f"{e.result.run_directory} {e.date_label}"
                ).casefold()
                for term in terms
            )
        ]
        self.table.setRowCount(0)
        for row, entry in enumerate(self._visible):
            self.table.insertRow(row)
            values = [
                entry_name(entry, self._preferences),
                str(entry.subjects) if entry.subjects is not None else "—",
                entry.date_label,
                "Trial fit" if entry.pilot else "Atlas",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(entry.result.run_directory))
                self.table.setItem(row, column, item)
        if self._visible:
            match = next(
                (
                    i
                    for i, e in enumerate(self._visible)
                    if previous is not None and e.result == previous.result
                ),
                0,
            )
            self.table.selectRow(match)
        if self._worker is None:
            count = len(self._visible)
            text = f"{count} result{'s' if count != 1 else ''}"
            if not self._scan.entries:
                text = "No completed results found. Add a project folder to search its subfolders."
            elif not count and not self.show_pilots.isChecked() and not terms:
                text = "Only trial fits found. Enable ‘Include trial fits’ to see them."
            if self._scan.incomplete:
                text += " · Search incomplete; add a more specific folder."
            if self._scan.unavailable:
                text += " · Some folders are unavailable."
            self.status.setText(text)
            self.status.setToolTip("\n".join(self._scan.unavailable))
        self._selection_changed()

    def _selected(self) -> ResultLibraryEntry | None:
        row = self.table.currentRow()
        return self._visible[row] if 0 <= row < len(self._visible) else None

    @Slot()
    def _selection_changed(self) -> None:
        entry = self._selected()
        enabled = entry is not None and self._worker is None
        self.open_button.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)
        self.location.setText(
            f"{entry.result.run_directory}\nFull verification runs when opened."
            if entry is not None
            else "Select a result to see its location."
        )

    @Slot()
    def _add_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose a project or dataset folder — subfolders are searched",
            str(self._roots[0]) if self._roots else "",
        )
        if selected:
            self._roots.insert(0, Path(selected))
            if not save_library_preference(root=Path(selected)):
                self.status.setToolTip("This folder could not be remembered for next time.")
            self.refresh()

    @Slot()
    def _rename(self) -> None:
        entry = self._selected()
        if entry is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Name result",
            "Display name (folders stay unchanged):",
            text=entry_name(entry, self._preferences),
        )
        if accepted:
            if save_library_preference(rename=(entry.result.run_directory, name)):
                self._preferences = load_library_preferences()
                self._filter()
            else:
                self.status.setText("The display name could not be saved.")

    @Slot()
    def _open(self) -> None:
        entry = self._selected()
        if entry is not None and self._worker is None:
            self.selected_result = entry.result
            self.accept()

    def done(self, result: int) -> None:
        self._closed = True
        if self._worker is not None:
            self._worker.cancelled.set()
        super().done(result)
