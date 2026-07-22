"""Guided orthographic vertex-landmark placement for homologous mesh cohorts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.analysis.landmarks import write_landmark_csv
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
from diffeoforge.desktop.mesh_preview_widget import MeshPreviewCanvas


class LandmarkEditorDialog(QDialog):
    """Place ordered vertex landmarks without modifying any source mesh."""

    def __init__(
        self,
        mesh_paths: tuple[Path, ...],
        output_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if len(mesh_paths) < 2:
            raise ValueError("Landmark placement requires a template and at least one subject")
        self.mesh_paths = tuple(path.expanduser().resolve() for path in mesh_paths)
        self.output_path = output_path.expanduser().resolve()
        self.labels = ["LM1", "LM2", "LM3"]
        self.placements: dict[str, dict[str, int]] = {
            path.name: {} for path in self.mesh_paths
        }
        self.models: dict[str, MeshPreviewModel] = {}
        self.setWindowTitle("Place homologous landmarks")
        self.resize(980, 760)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Click the same anatomical vertex for every landmark on every mesh. Change "
            "projection whenever a point is occluded. DiffeoForge stores exact 3D vertex "
            "coordinates and never modifies the source meshes."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        selectors = QHBoxLayout()
        self.mesh_combo = QComboBox()
        for index, path in enumerate(self.mesh_paths):
            role = "Template" if index == 0 else f"Subject {index}"
            self.mesh_combo.addItem(f"{role}: {path.name}", path.name)
        self.mesh_combo.currentIndexChanged.connect(self._load_current_mesh)
        self.label_combo = QComboBox()
        self.label_combo.addItems(self.labels)
        self.label_combo.currentIndexChanged.connect(self._sync_canvas_markers)
        self.plane_combo = QComboBox()
        self.plane_combo.addItem("XY · view along Z", "xy")
        self.plane_combo.addItem("XZ · view along Y", "xz")
        self.plane_combo.addItem("YZ · view along X", "yz")
        self.plane_combo.currentIndexChanged.connect(self._change_plane)
        selectors.addWidget(QLabel("Mesh"))
        selectors.addWidget(self.mesh_combo, 2)
        selectors.addWidget(QLabel("Landmark"))
        selectors.addWidget(self.label_combo, 1)
        selectors.addWidget(QLabel("Projection"))
        selectors.addWidget(self.plane_combo, 1)
        layout.addLayout(selectors)

        label_buttons = QHBoxLayout()
        add_label = QPushButton("Add landmark label")
        add_label.clicked.connect(self._add_label)
        remove_label = QPushButton("Remove current label")
        remove_label.clicked.connect(self._remove_label)
        clear_current = QPushButton("Clear current point")
        clear_current.clicked.connect(self._clear_current)
        label_buttons.addWidget(add_label)
        label_buttons.addWidget(remove_label)
        label_buttons.addWidget(clear_current)
        label_buttons.addStretch()
        layout.addLayout(label_buttons)

        self.canvas = MeshPreviewCanvas()
        self.canvas.setMinimumHeight(520)
        self.canvas.set_picking_enabled(True)
        self.canvas.vertexPicked.connect(self._place_vertex)
        layout.addWidget(self.canvas, 1)

        navigation = QHBoxLayout()
        previous_mesh = QPushButton("Previous mesh")
        previous_mesh.clicked.connect(lambda: self._move_mesh(-1))
        next_mesh = QPushButton("Next mesh")
        next_mesh.clicked.connect(lambda: self._move_mesh(1))
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(previous_mesh)
        navigation.addWidget(self.status_label, 1)
        navigation.addWidget(next_mesh)
        layout.addLayout(navigation)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Save landmark CSV"
        )
        self.buttons.accepted.connect(self._save_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._load_current_mesh()

    def _current_mesh_name(self) -> str:
        return str(self.mesh_combo.currentData())

    def _current_label(self) -> str:
        return self.label_combo.currentText()

    @Slot()
    def _load_current_mesh(self) -> None:
        path = self.mesh_paths[self.mesh_combo.currentIndex()]
        model = self.models.get(path.name)
        if model is None:
            model = load_mesh_preview(path)
            self.models[path.name] = model
        self.canvas.set_model(model)
        self.canvas.set_plane(self.plane_combo.currentData())
        self._sync_canvas_markers()

    @Slot()
    def _change_plane(self) -> None:
        self.canvas.set_plane(self.plane_combo.currentData())

    @Slot()
    def _sync_canvas_markers(self) -> None:
        placements = self.placements[self._current_mesh_name()]
        ordered = {label: placements[label] for label in self.labels if label in placements}
        self.canvas.set_markers(ordered)
        placed = sum(len(values) for values in self.placements.values())
        total = len(self.mesh_paths) * len(self.labels)
        current = "placed" if self._current_label() in placements else "not placed"
        self.status_label.setText(
            f"{placed} of {total} points placed · current landmark {current}"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(
            placed == total and len(self.labels) >= 3
        )

    @Slot(int)
    def _place_vertex(self, vertex_index: int) -> None:
        self.placements[self._current_mesh_name()][self._current_label()] = vertex_index
        self._sync_canvas_markers()
        next_label = self.label_combo.currentIndex() + 1
        if next_label < self.label_combo.count():
            self.label_combo.setCurrentIndex(next_label)
        elif self.mesh_combo.currentIndex() + 1 < self.mesh_combo.count():
            self.mesh_combo.setCurrentIndex(self.mesh_combo.currentIndex() + 1)
            self.label_combo.setCurrentIndex(0)

    @Slot()
    def _add_label(self) -> None:
        label, accepted = QInputDialog.getText(
            self, "Add landmark", "Unique anatomical landmark label:"
        )
        label = label.strip()
        if not accepted or not label:
            return
        if label in self.labels:
            QMessageBox.warning(self, "Duplicate label", "Landmark labels must be unique.")
            return
        self.labels.append(label)
        self.label_combo.addItem(label)
        self.label_combo.setCurrentIndex(self.label_combo.count() - 1)
        self._sync_canvas_markers()

    @Slot()
    def _remove_label(self) -> None:
        if len(self.labels) <= 3:
            QMessageBox.warning(
                self,
                "At least three landmarks required",
                "Generalized Procrustes requires at least three non-collinear landmarks.",
            )
            return
        label = self._current_label()
        self.labels.remove(label)
        for placements in self.placements.values():
            placements.pop(label, None)
        self.label_combo.removeItem(self.label_combo.currentIndex())
        self._sync_canvas_markers()

    @Slot()
    def _clear_current(self) -> None:
        self.placements[self._current_mesh_name()].pop(self._current_label(), None)
        self._sync_canvas_markers()

    def _move_mesh(self, offset: int) -> None:
        target = max(0, min(self.mesh_combo.count() - 1, self.mesh_combo.currentIndex() + offset))
        self.mesh_combo.setCurrentIndex(target)

    @Slot()
    def _save_and_accept(self) -> None:
        if not self.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled():
            return
        values = np.empty((len(self.mesh_paths), len(self.labels), 3), dtype=np.float64)
        for mesh_index, path in enumerate(self.mesh_paths):
            model = self.models[path.name]
            for landmark_index, label in enumerate(self.labels):
                values[mesh_index, landmark_index] = model.vertices[
                    self.placements[path.name][label]
                ]
        overwrite = False
        if self.output_path.exists():
            overwrite = (
                QMessageBox.question(
                    self,
                    "Overwrite landmark CSV?",
                    f"The landmark file already exists:\n{self.output_path}\n\nOverwrite it?",
                )
                == QMessageBox.StandardButton.Yes
            )
            if not overwrite:
                return
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        write_landmark_csv(
            self.output_path,
            tuple(path.name for path in self.mesh_paths),
            tuple(self.labels),
            values,
            overwrite=overwrite,
        )
        self.accept()
