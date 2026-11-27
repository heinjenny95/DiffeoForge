"""Choose a metadata contrast between two existing, independently verified atlases."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.notifications import notify
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.result_library_dialog import ResultLibraryDialog
from diffeoforge.mesh import sha256_file


def _metadata_choices(path: Path):
    raw = path.read_bytes()
    rows = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    fields = tuple(value.strip() for value in next(rows, ()))
    if len(fields) < 2 or not all(fields) or len(set(fields)) != len(fields):
        raise ValueError("The CSV needs unique subject-ID and group column headers.")
    values = {field: set() for field in fields}
    for line, row in enumerate(rows, start=2):
        if not any(value.strip() for value in row):
            continue
        if len(row) != len(fields):
            raise ValueError(f"CSV row {line} has a different number of cells than the header.")
        for field, value in zip(fields, row, strict=True):
            if value.strip():
                values[field].add(value.strip())
    if not any(values.values()):
        raise ValueError("The metadata CSV has no specimen rows.")
    return hashlib.sha256(raw).hexdigest(), {
        field: tuple(sorted(choices, key=lambda value: (value.casefold(), value)))
        for field, choices in values.items()
    }


class GroupAtlasComparisonDialog(QDialog):
    """Compare a chosen pair of levels on the same specimens in two saved results."""

    def __init__(self, first_directory: Path, parent=None) -> None:
        super().__init__(parent)
        self.first_directory = Path(first_directory).resolve()
        self._second: Path | None = None
        self._metadata: Path | None = None
        self._metadata_sha: str | None = None
        self._values: dict[str, tuple[str, ...]] = {}
        self._busy = False
        self._writing = False
        self._report: Path | None = None
        self.setWindowTitle("Compare group effects across atlases")
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        intro = QLabel("Use one metadata contrast on both saved atlases. The report describes "
                       "group separation in the verified shape spaces.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        inputs = QFormLayout()
        self.first_edit = QLineEdit(str(self.first_directory))
        self.first_edit.setReadOnly(True)
        inputs.addRow("Current atlas", self.first_edit)
        self.second_edit, self.choose_second = self._browse_row(
            inputs, "Second atlas", "Choose result…", self._choose_second,
        )
        self.metadata_edit, self.choose_metadata = self._browse_row(
            inputs, "Metadata CSV", "Browse…", self._choose_metadata,
        )
        self.ids = self._field(inputs, "Subject ID column", "Choose an ID column")
        self.groups = self._field(inputs, "Group column", "Choose a group column")
        self.reference = self._field(inputs, "Reference group", "Choose a reference level")
        self.comparison = self._field(inputs, "Comparison group", "Choose a comparison level")
        layout.addLayout(inputs)
        self.status = QLabel("Choose another atlas and a specimen metadata CSV.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        layout.addStretch()
        actions = QHBoxLayout()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        self.open_report = QPushButton("Open report")
        self.open_report.setObjectName("secondary")
        self.open_report.clicked.connect(self._open_report)
        self.open_report.hide()
        self.create = QPushButton("Create comparison report")
        self.create.setObjectName("primary")
        self.create.clicked.connect(self._create_report)
        self.create.setDefault(True)
        actions.addWidget(self.close_button)
        actions.addStretch()
        self.trace_point = QPushButton("Trace a template point…")
        self.trace_point.setObjectName("secondary")
        self.trace_point.clicked.connect(self._trace_point)
        actions.addWidget(self.trace_point)
        actions.addWidget(self.open_report)
        actions.addWidget(self.create)
        layout.addLayout(actions)
        self._loader = PreviewMeshLoader(self)
        self._loader.activity_changed.connect(self._set_busy)
        self._loader.loaded.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self.finished.connect(self._loader.cancel)
        self.ids.currentIndexChanged.connect(self._update_groups)
        self.groups.currentIndexChanged.connect(self._update_levels)
        self.reference.currentIndexChanged.connect(self._contrast_changed)
        self.comparison.currentIndexChanged.connect(self._contrast_changed)
        self._update_actions()

    @staticmethod
    def _browse_row(layout, label, button_label, action):
        row = QWidget()
        controls = QHBoxLayout(row)
        controls.setContentsMargins(0, 0, 0, 0)
        location = QLineEdit()
        location.setReadOnly(True)
        location.setAccessibleName(label)
        button = QPushButton(button_label)
        button.clicked.connect(action)
        controls.addWidget(location, 1)
        controls.addWidget(button)
        layout.addRow(label, row)
        return location, button

    @staticmethod
    def _field(layout, label, prompt):
        combo = QComboBox()
        combo.setAccessibleName(label)
        combo.setPlaceholderText(prompt)
        layout.addRow(label, combo)
        return combo

    def _select_second(self, path: Path):
        path = path.resolve()
        if path == self.first_directory:
            self._second = None
            self.second_edit.clear()
            self._contrast_changed()
            self.status.setText("Choose a different completed atlas for this comparison.")
            return
        self._second = path
        self.second_edit.setText(str(path))
        self._contrast_changed()

    @Slot()
    def _choose_second(self):
        chooser = ResultLibraryDialog(self.first_directory.parent, self)
        chooser.setWindowTitle("Choose the second atlas")
        try:
            if chooser.exec() == QDialog.DialogCode.Accepted and chooser.selected_result:
                self._select_second(chooser.selected_result.run_directory)
        finally:
            chooser.deleteLater()

    def _select_metadata(self, path: Path):
        self._metadata = path.resolve()
        self._metadata_sha = None
        self._values = {}
        self.metadata_edit.setText(str(self._metadata))
        self.ids.clear()
        self._update_groups()
        self.status.setText("Reading metadata columns…")
        selected = self._metadata
        self._loader.request_operation(("metadata", selected), lambda: _metadata_choices(selected))

    @Slot()
    def _choose_metadata(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select specimen metadata CSV", str(self.first_directory.parent),
            "CSV files (*.csv);;All files (*)",
        )
        if selected:
            self._select_metadata(Path(selected))

    @Slot()
    def _update_groups(self):
        previous = self.groups.currentText() or "group"
        self.groups.blockSignals(True)
        self.groups.clear()
        if self.ids.currentIndex() >= 0:
            self.groups.addItems([name for name, levels in self._values.items()
                                  if name != self.ids.currentText() and len(levels) > 1])
            self.groups.setCurrentIndex(self.groups.findText(previous))
        self.groups.blockSignals(False)
        self._update_levels()

    @Slot()
    def _update_levels(self):
        available = self._values.get(self.groups.currentText(), ())
        for combo in (self.reference, self.comparison):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(available)
            combo.setCurrentIndex(-1)
            combo.blockSignals(False)
        self._contrast_changed()

    @Slot()
    def _contrast_changed(self):
        if self._report is not None:
            self._report = None
            self.status.setText("Create a report for the updated contrast.")
        self._update_actions()

    @Slot()
    def _update_actions(self):
        free = not (self._busy or self._writing)
        self.choose_second.setEnabled(free)
        self.choose_metadata.setEnabled(free)
        self.ids.setEnabled(free and bool(self._values))
        self.groups.setEnabled(free and self.ids.currentIndex() >= 0)
        for combo in (self.reference, self.comparison):
            combo.setEnabled(free and self.groups.currentIndex() >= 0)
        self.close_button.setEnabled(not self._writing)
        self.trace_point.setEnabled(free and self._second is not None)
        self.open_report.setVisible(self._report is not None)
        self.open_report.setEnabled(free and self._report is not None)
        self.create.setEnabled(bool(
            free and self._second and self._metadata_sha and self.ids.currentIndex() >= 0
            and self.groups.currentIndex() >= 0 and self.reference.currentIndex() >= 0
            and self.comparison.currentIndex() >= 0
            and self.reference.currentText() != self.comparison.currentText()
        ))

    @Slot(bool)
    def _set_busy(self, busy):
        self._busy = busy
        self._update_actions()

    @Slot()
    def _create_report(self):
        if not self.create.isEnabled():
            return
        self._report = None
        first, second, metadata = self.first_directory, self._second, self._metadata
        metadata_sha = self._metadata_sha
        choices = dict(id_column=self.ids.currentText(), group_column=self.groups.currentText(),
                       reference_level=self.reference.currentText(),
                       comparison_level=self.comparison.currentText())
        destination = first.with_name(f"{first.name}-group-comparison-{uuid4().hex[:10]}")
        self._writing = True
        self.status.setText("Verifying both saved atlases and creating the comparison report…")

        def write():
            from diffeoforge.biological_atlas_comparison import write_group_comparison

            if sha256_file(metadata) != metadata_sha:
                raise ValueError("The CSV changed. Select it again to reload the group choices.")
            result = Path(write_group_comparison(first, second, metadata, destination, **choices))
            resolved = result.resolve(strict=True)
            if (not resolved.is_file() or not resolved.is_relative_to(destination.resolve())
                    or resolved.suffix.lower() != ".html"):
                raise ValueError("The comparison did not create a local HTML report.")
            return resolved

        self._loader.request_operation(("report", destination), write)

    @Slot(object, object)
    def _loaded(self, key, value):
        kind, source = key
        if kind == "metadata" and source == self._metadata:
            self._metadata_sha, self._values = value
            self.ids.blockSignals(True)
            self.ids.addItems(self._values.keys())
            self.ids.setCurrentIndex(self.ids.findText("subject"))
            self.ids.blockSignals(False)
            self._update_groups()
            self.status.setText("Choose the subject ID column and two different group levels.")
        elif kind == "report":
            self._writing = False
            self._report = value
            notify(self, "Atlas comparison finished", "The group comparison report is ready.")
            self.status.setText(f"Comparison report ready. Saved in {value.parent}")
        self._update_actions()

    @Slot(object, str)
    def _failed(self, key, message):
        if key[0] == "report":
            self._writing = False
            notify(self, "Atlas comparison needs attention", "Open the comparison for details.",
                   warning=True)
        self.status.setText(f"Comparison could not be prepared. {message}")
        self._update_actions()

    @Slot()
    def _trace_point(self):
        if not self.trace_point.isEnabled() or self._second is None:
            return
        from diffeoforge.desktop.atlas_correspondence_dialog import AtlasCorrespondenceDialog

        dialog = AtlasCorrespondenceDialog(self.first_directory, self._second, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    @Slot()
    def _open_report(self):
        if (self._report is not None and self._report.is_file()
                and self._report.resolve() == self._report):
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report))):
                self.status.setText(f"Could not open the report. Saved at {self._report}")

    def done(self, result):
        if not self._writing:
            super().done(result)
