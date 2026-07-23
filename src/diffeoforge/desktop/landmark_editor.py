"""Guided interactive 3D landmark placement for homologous mesh cohorts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
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
from diffeoforge.atomic_io import write_text_safely
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
from diffeoforge.mesh import sha256_file

SurfacePoint = tuple[float, float, float]


class LandmarkEditorDialog(QDialog):
    """Place ordered surface landmarks without modifying any source mesh."""

    def __init__(
        self,
        mesh_paths: tuple[Path, ...],
        output_path: Path,
        parent=None,
        *,
        initial_landmark_count: int = 3,
        auto_advance_mesh: bool = True,
    ) -> None:
        super().__init__(parent)
        if len(mesh_paths) < 2:
            raise ValueError("Landmark placement requires a template and at least one subject")
        if (
            isinstance(initial_landmark_count, bool)
            or not isinstance(initial_landmark_count, int)
            or initial_landmark_count < 3
        ):
            raise ValueError(
                "Generalized Procrustes requires at least three non-collinear landmarks"
            )
        if not isinstance(auto_advance_mesh, bool):
            raise ValueError("Automatic mesh advancement must be enabled or disabled")
        self.mesh_paths = tuple(path.expanduser().resolve() for path in mesh_paths)
        if len({path.name for path in self.mesh_paths}) != len(self.mesh_paths):
            raise ValueError("Landmark placement requires unique mesh filenames")
        self.output_path = output_path.expanduser().resolve()
        self._draft_owned = True
        self.labels = [
            f"LM{index}" for index in range(1, initial_landmark_count + 1)
        ]
        self.placements: dict[str, dict[str, SurfacePoint]] = {
            path.name: {} for path in self.mesh_paths
        }
        self._placement_history: list[tuple[str, str, SurfacePoint | None]] = []
        self.models: dict[str, MeshPreviewModel] = {}
        self._known_mesh_hashes: dict[str, str] = {}
        self.setWindowTitle("Place homologous landmarks")
        self.resize(1180, 840)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Place each label on the same anatomical location for every mesh. Rotate and "
            "zoom the specimen, then click the visible surface. A new click replaces the "
            "selected point. DiffeoForge stores exact 3D surface coordinates and never "
            "modifies the source meshes. Progress is autosaved; Cancel keeps the draft."
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
        self.view_combo = QComboBox()
        self.view_combo.addItem("3/4 view", "three-quarter")
        self.view_combo.addItem("Front", "front")
        self.view_combo.addItem("Back", "back")
        self.view_combo.addItem("Left", "left")
        self.view_combo.addItem("Right", "right")
        self.view_combo.addItem("Top", "top")
        self.view_combo.addItem("Bottom", "bottom")
        self.view_combo.currentIndexChanged.connect(self._change_view)
        reset_view = QPushButton("Reset view")
        reset_view.setObjectName("secondary")
        reset_view.clicked.connect(self._reset_view)
        selectors.addWidget(QLabel("Mesh"))
        selectors.addWidget(self.mesh_combo, 2)
        selectors.addWidget(QLabel("Landmark"))
        selectors.addWidget(self.label_combo, 1)
        selectors.addWidget(QLabel("View"))
        selectors.addWidget(self.view_combo, 1)
        selectors.addWidget(reset_view)
        layout.addLayout(selectors)

        label_buttons = QHBoxLayout()
        add_label = QPushButton("Add landmark label")
        add_label.clicked.connect(self._add_label)
        rename_label = QPushButton("Rename current label")
        rename_label.clicked.connect(self._rename_label)
        remove_label = QPushButton("Remove current label")
        remove_label.clicked.connect(self._remove_label)
        clear_current = QPushButton("Clear current point")
        clear_current.clicked.connect(self._clear_current)
        self.undo_button = QPushButton("Undo last placement")
        self.undo_button.clicked.connect(self._undo_last_placement)
        self.undo_button.setEnabled(False)
        label_buttons.addWidget(add_label)
        label_buttons.addWidget(rename_label)
        label_buttons.addWidget(remove_label)
        label_buttons.addWidget(clear_current)
        label_buttons.addWidget(self.undo_button)
        label_buttons.addStretch()
        layout.addLayout(label_buttons)

        self.auto_advance_mesh_check = QCheckBox(
            "Automatically load the next mesh after all planned landmarks are placed"
        )
        self.auto_advance_mesh_check.setObjectName("autoAdvanceLandmarkMeshCheck")
        self.auto_advance_mesh_check.setChecked(auto_advance_mesh)
        self.auto_advance_mesh_check.setToolTip(
            "When disabled, the completed mesh remains visible until you use Next mesh "
            "or select another mesh."
        )
        layout.addWidget(self.auto_advance_mesh_check)

        self.canvas = InteractiveMeshCanvas3D()
        self.canvas.surfacePointPicked.connect(self._place_surface_point)
        layout.addWidget(self.canvas, 1)

        navigation = QHBoxLayout()
        previous_mesh = QPushButton("Previous mesh")
        previous_mesh.clicked.connect(lambda: self._move_mesh(-1))
        next_mesh = QPushButton("Next mesh")
        next_mesh.clicked.connect(lambda: self._move_mesh(1))
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.draft_status_label = QLabel("No landmark draft has been written yet.")
        self.draft_status_label.setStyleSheet("color: #52666b;")
        self.draft_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(previous_mesh)
        progress = QVBoxLayout()
        progress.setSpacing(2)
        progress.addWidget(self.status_label)
        progress.addWidget(self.draft_status_label)
        navigation.addLayout(progress, 1)
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
        self.auto_advance_mesh_check.toggled.connect(
            self._auto_advance_mesh_changed
        )
        self._restore_draft_if_available()
        self._load_current_mesh()

    @property
    def draft_path(self) -> Path:
        return self.output_path.with_suffix(f"{self.output_path.suffix}.draft.json")

    def _draft_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "saved_at_utc": datetime.now(UTC).isoformat(),
            "output_path": str(self.output_path),
            "mesh_paths": [str(path) for path in self.mesh_paths],
            "mesh_sha256": dict(sorted(self._known_mesh_hashes.items())),
            "labels": list(self.labels),
            "auto_advance_mesh": self.auto_advance_mesh_check.isChecked(),
            "placements": {
                mesh_name: {
                    label: list(point)
                    for label, point in sorted(mesh_placements.items())
                }
                for mesh_name, mesh_placements in sorted(self.placements.items())
            },
        }

    def _save_draft(self) -> None:
        if not self._draft_owned:
            self.draft_status_label.setText(
                "Autosave paused to protect the existing draft that was not loaded."
            )
            self.draft_status_label.setStyleSheet("color: #a56700;")
            return
        try:
            write_text_safely(
                self.draft_path,
                json.dumps(self._draft_payload(), indent=2, sort_keys=True) + "\n",
                overwrite=True,
                encoding="utf-8",
            )
        except OSError as error:
            self.draft_status_label.setText(f"Draft autosave failed: {error}")
            self.draft_status_label.setStyleSheet("color: #a93419;")
            return
        self.draft_status_label.setText(f"Progress autosaved: {self.draft_path.name}")
        self.draft_status_label.setStyleSheet("color: #167c6b;")

    def _restore_draft_if_available(self) -> None:
        if not self.draft_path.is_file():
            return
        if (
            QMessageBox.question(
                self,
                "Resume landmark draft?",
                f"DiffeoForge found autosaved landmark progress:\n{self.draft_path}\n\n"
                "Validate its mesh identities and resume it?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            self._draft_owned = False
            self.draft_status_label.setText(
                "Existing draft was not loaded; autosave is paused to protect it."
            )
            self.draft_status_label.setStyleSheet("color: #a56700;")
            return
        try:
            payload = json.loads(self.draft_path.read_text(encoding="utf-8"))
            schema_version = payload.get("schema_version")
            if schema_version not in (1, 2):
                raise ValueError("unsupported draft schema version")
            expected_paths = [str(path) for path in self.mesh_paths]
            if payload.get("mesh_paths") != expected_paths:
                raise ValueError("the draft belongs to a different mesh cohort")
            labels = payload.get("labels")
            if (
                not isinstance(labels, list)
                or len(labels) < 3
                or not all(isinstance(label, str) and label.strip() for label in labels)
                or len(set(labels)) != len(labels)
            ):
                raise ValueError("the draft contains invalid landmark labels")
            hashes = payload.get("mesh_sha256")
            placements = payload.get("placements")
            if not isinstance(hashes, dict) or not isinstance(placements, dict):
                raise ValueError("the draft is missing identity or placement records")
            auto_advance_mesh = (
                payload.get("auto_advance_mesh")
                if schema_version == 2
                else self.auto_advance_mesh_check.isChecked()
            )
            if not isinstance(auto_advance_mesh, bool):
                raise ValueError("the draft contains an invalid auto-advance setting")
            restored: dict[str, dict[str, SurfacePoint]] = {
                path.name: {} for path in self.mesh_paths
            }
            path_by_name = {path.name: path for path in self.mesh_paths}
            for mesh_name, mesh_placements in placements.items():
                if mesh_name not in path_by_name or not isinstance(mesh_placements, dict):
                    raise ValueError("the draft contains an unexpected mesh record")
                if mesh_placements:
                    expected_hash = hashes.get(mesh_name)
                    if not isinstance(expected_hash, str):
                        raise ValueError(f"the draft has no hash for {mesh_name}")
                    if sha256_file(path_by_name[mesh_name]) != expected_hash:
                        raise ValueError(f"source mesh changed since the draft: {mesh_name}")
                for label, point in mesh_placements.items():
                    if label not in labels or not isinstance(point, list) or len(point) != 3:
                        raise ValueError("the draft contains an invalid surface point")
                    values = tuple(float(value) for value in point)
                    if not all(np.isfinite(value) for value in values):
                        raise ValueError("the draft contains a non-finite surface point")
                    restored[mesh_name][label] = values
        except (OSError, TypeError, ValueError) as error:
            self._draft_owned = False
            QMessageBox.warning(
                self,
                "Landmark draft could not be resumed",
                f"The existing draft was not loaded: {error}",
            )
            self.draft_status_label.setText("Existing draft failed validation and was not loaded.")
            return
        self.labels = list(labels)
        self._draft_owned = True
        self.placements = restored
        self._known_mesh_hashes = {
            str(mesh_name): str(hash_value)
            for mesh_name, hash_value in hashes.items()
            if mesh_name in path_by_name and isinstance(hash_value, str)
        }
        self.label_combo.clear()
        self.label_combo.addItems(self.labels)
        self.auto_advance_mesh_check.blockSignals(True)
        self.auto_advance_mesh_check.setChecked(auto_advance_mesh)
        self.auto_advance_mesh_check.blockSignals(False)
        self.draft_status_label.setText("Validated autosaved progress was resumed.")
        self.draft_status_label.setStyleSheet("color: #167c6b;")

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
        self._known_mesh_hashes[path.name] = model.sha256
        self.canvas.set_model(model)
        self._sync_canvas_markers()

    @Slot()
    def _change_view(self) -> None:
        self.canvas.set_view_preset(str(self.view_combo.currentData()))

    @Slot()
    def _reset_view(self) -> None:
        self.view_combo.setCurrentIndex(0)
        self.canvas.reset_view()

    @Slot()
    def _sync_canvas_markers(self) -> None:
        placements = self.placements[self._current_mesh_name()]
        ordered = {label: placements[label] for label in self.labels if label in placements}
        self.canvas.set_markers(ordered)
        placed = sum(len(values) for values in self.placements.values())
        total = len(self.mesh_paths) * len(self.labels)
        current = (
            "placed — click the surface to replace"
            if self._current_label() in placements
            else "not placed"
        )
        self.status_label.setText(
            f"{placed} of {total} points placed · current landmark {current}"
        )
        self.undo_button.setEnabled(bool(self._placement_history))
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(
            placed == total and len(self.labels) >= 3
        )

    @Slot(object)
    def _place_surface_point(self, point: object) -> None:
        values = tuple(float(value) for value in point)  # type: ignore[arg-type]
        if len(values) != 3 or not all(np.isfinite(value) for value in values):
            raise ValueError("A landmark must contain three finite surface coordinates")
        mesh_name = self._current_mesh_name()
        label = self._current_label()
        previous = self.placements[mesh_name].get(label)
        self._placement_history.append((mesh_name, label, previous))
        self.placements[mesh_name][label] = values
        self._sync_canvas_markers()
        self._save_draft()
        next_label = self.label_combo.currentIndex() + 1
        if next_label < self.label_combo.count():
            self.label_combo.setCurrentIndex(next_label)
        elif (
            self.auto_advance_mesh_check.isChecked()
            and all(label in self.placements[mesh_name] for label in self.labels)
            and self.mesh_combo.currentIndex() + 1 < self.mesh_combo.count()
        ):
            self.mesh_combo.setCurrentIndex(self.mesh_combo.currentIndex() + 1)
            self.label_combo.setCurrentIndex(0)

    @Slot(bool)
    def _auto_advance_mesh_changed(self, _checked: bool) -> None:
        self._save_draft()

    @Slot()
    def _undo_last_placement(self) -> None:
        if not self._placement_history:
            return
        mesh_name, label, previous = self._placement_history.pop()
        if previous is None:
            self.placements[mesh_name].pop(label, None)
        else:
            self.placements[mesh_name][label] = previous
        mesh_index = next(
            index
            for index in range(self.mesh_combo.count())
            if self.mesh_combo.itemData(index) == mesh_name
        )
        self.mesh_combo.setCurrentIndex(mesh_index)
        self.label_combo.setCurrentIndex(self.labels.index(label))
        self._sync_canvas_markers()
        self._save_draft()

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
        self._save_draft()

    @Slot()
    def _rename_label(self) -> None:
        previous_label = self._current_label()
        label, accepted = QInputDialog.getText(
            self,
            "Rename landmark",
            "Unique anatomical landmark label:",
            text=previous_label,
        )
        label = label.strip()
        if not accepted or label == previous_label:
            return
        if not label or label in self.labels:
            QMessageBox.warning(
                self,
                "Invalid label",
                "Landmark labels must be non-empty and unique.",
            )
            return
        index = self.labels.index(previous_label)
        self.labels[index] = label
        for placements in self.placements.values():
            if previous_label in placements:
                placements[label] = placements.pop(previous_label)
        self._placement_history = [
            (mesh_name, label if item_label == previous_label else item_label, previous)
            for mesh_name, item_label, previous in self._placement_history
        ]
        self.label_combo.setItemText(index, label)
        self.label_combo.setCurrentIndex(index)
        self._sync_canvas_markers()
        self._save_draft()

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
        self._placement_history = [
            item for item in self._placement_history if item[1] != label
        ]
        self.label_combo.removeItem(self.label_combo.currentIndex())
        self._sync_canvas_markers()
        self._save_draft()

    @Slot()
    def _clear_current(self) -> None:
        mesh_name = self._current_mesh_name()
        label = self._current_label()
        previous = self.placements[mesh_name].pop(label, None)
        if previous is not None:
            self._placement_history.append((mesh_name, label, previous))
        self._sync_canvas_markers()
        self._save_draft()

    def _move_mesh(self, offset: int) -> None:
        target = max(
            0,
            min(self.mesh_combo.count() - 1, self.mesh_combo.currentIndex() + offset),
        )
        self.mesh_combo.setCurrentIndex(target)

    @Slot()
    def _save_and_accept(self) -> None:
        if not self.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled():
            return
        for path in self.mesh_paths:
            expected_hash = self._known_mesh_hashes.get(path.name)
            try:
                current_hash = sha256_file(path)
            except OSError as error:
                QMessageBox.warning(
                    self,
                    "Source mesh identity unavailable",
                    f"The landmark CSV was not written because this source mesh could not "
                    f"be verified:\n{path}\n\n{error}",
                )
                return
            if expected_hash is None or current_hash != expected_hash:
                QMessageBox.warning(
                    self,
                    "Source mesh identity changed",
                    f"The landmark CSV was not written because this source mesh no longer "
                    f"matches the geometry used for placement:\n{path}",
                )
                return
        values = np.empty((len(self.mesh_paths), len(self.labels), 3), dtype=np.float64)
        for mesh_index, path in enumerate(self.mesh_paths):
            for landmark_index, label in enumerate(self.labels):
                values[mesh_index, landmark_index] = self.placements[path.name][label]
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
        if self._draft_owned:
            self.draft_path.unlink(missing_ok=True)
        self.accept()
