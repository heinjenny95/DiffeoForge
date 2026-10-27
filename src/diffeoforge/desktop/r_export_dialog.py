"""Explicit, background R handoffs from selected inputs or a reviewed result."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.r_export import export_landmarks_to_r, export_pca_to_r

_EXPORTS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="r-handoff")


class RExportDialog(QDialog):
    def __init__(self, parent=None, *, review=None, landmarks=None, meshes=(), unit=None):
        super().__init__(parent)
        self.review, self.landmarks, self.meshes, self.unit = review, landmarks, meshes, unit
        self.future = None
        self.setWindowTitle("Export data for R")
        self.resize(760, 440)
        layout = QVBoxLayout(self)
        title = QLabel("Continue your analysis in R")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.mode = QComboBox()
        self.mode.setAccessibleName("R export data type")
        self.mode.addItem("Saved atlas PCA → base R", "pca")
        self.mode.addItem("Homologous landmarks → geomorph", "geomorph")
        self.mode.model().item(0).setEnabled(review is not None)
        has_landmarks = landmarks is not None and len(meshes) >= 3 and Path(landmarks).is_file()
        self.mode.model().item(1).setEnabled(has_landmarks)
        if review is None and has_landmarks:
            self.mode.setCurrentIndex(1)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.source = QLabel()
        self.source.setWordWrap(True)
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.availability = QLabel()
        self.availability.setWordWrap(True)
        self.availability.setTextFormat(Qt.TextFormat.PlainText)
        self.status = QLabel("A ZIP contains the data, R scripts and source provenance.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.mode)
        layout.addWidget(self.availability)
        layout.addWidget(self.description)
        layout.addWidget(self.source)
        layout.addStretch()
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("secondary")
        self.close_button.clicked.connect(self.reject)
        self.export_button = QPushButton("Save data for R (ZIP)…")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.close_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._finished)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self):
        pca = self.mode.currentData() == "pca"
        has_landmarks = (self.landmarks is not None and len(self.meshes) >= 3
                         and Path(self.landmarks).is_file())
        self.mode.model().item(1).setEnabled(has_landmarks)
        self.availability.setText(
            ("Base R: reviewed PCA selected." if self.review is not None
             else "Base R: open a reviewed atlas result first.") + "\n" +
            (f"geomorph: landmark CSV selected for {len(self.meshes)-1} subjects; "
             "checked during export." if has_landmarks else
             "geomorph: select an existing landmark CSV, template and at least two subjects.")
        )
        self.description.setText(
            "Export the exact saved specimen scores, explained variance and available loadings. "
            "The base R script loads them without recomputing PCA. No atlas is refitted."
            if pca else
            "Export the supplied fixed landmark coordinates as a landmarks × 3 × specimens "
            "array. The template is excluded. A base R loader and an optional geomorph "
            "GPA/PCA example are included. This landmark analysis differs from the atlas PCA."
        )
        available = self.review is not None if pca else has_landmarks
        self.export_button.setEnabled(available and self.future is None)
        self.source.setText(
            (f"Reviewed result: {self.review.project_name}\nMethod: {self.review.pca_method_label}"
             if self.review is not None else "Open a reviewed atlas result for this export.")
            if pca else
            (f"Landmark CSV: {self.landmarks}\n{len(self.meshes)-1} subjects; source coordinates "
             "and units are retained. Inspect landmark homology before using geomorph."
             f" Units: {self.unit or 'not declared'}; no unit conversion."
             if available else "Select a complete landmark CSV and mesh cohort in Inputs first.")
        )

    def _export(self):
        if self.future is not None or not self.export_button.isEnabled():
            return
        pca = self.mode.currentData() == "pca"
        name = "DiffeoForge-PCA-for-R.zip" if pca else "DiffeoForge-landmarks-for-geomorph.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Save R handoff", name, "ZIP (*.zip)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".zip")
        self.export_button.setEnabled(False)
        self.mode.setEnabled(False)
        self.status.setText("Verifying sources and writing the data ZIP…")
        if pca:
            self.future = _EXPORTS.submit(export_pca_to_r, self.review, target)
        else:
            self.future = _EXPORTS.submit(
                export_landmarks_to_r, self.landmarks,
                tuple(path.name for path in self.meshes), target,
                template_name=self.meshes[0].name, coordinate_unit=self.unit,
            )
        self.timer.start()

    def _finished(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        self.mode.setEnabled(True)
        self._mode_changed()
        try:
            path = future.result()
            self.status.setText(
                f"Saved and byte-verified: {path}\nExtract the ZIP and follow README."
            )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            self.status.setText(f"Export unavailable: {error}")

    def reject(self):
        if self.future is not None:
            self.status.setText("The export is finishing. You can close this window afterwards.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.future is not None:
            event.ignore()
        else:
            super().closeEvent(event)
