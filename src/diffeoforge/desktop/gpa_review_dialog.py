"""Guided visual inspection of one exact GPA-aligned cohort."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from diffeoforge.desktop.gpa_visualization import (
    GpaAlignmentVisual,
)
from diffeoforge.desktop.gpa_visualization_widget import GpaAlignmentCanvas3D
from diffeoforge.preprocessing import LandmarkAlignmentPreview


class GpaAlignmentReviewDialog(QDialog):
    """Inspect transformed meshes before approving a GPA preview."""

    previewInvalidated = Signal(str)

    def __init__(
        self,
        preview: LandmarkAlignmentPreview,
        visual: GpaAlignmentVisual,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if preview.fingerprint != visual.fingerprint:
            raise ValueError("Visual and numerical GPA previews have different fingerprints")
        if len(preview.source_paths) != len(visual.meshes):
            raise ValueError("Visual and numerical GPA previews have different cohorts")
        self.preview = preview
        self.visual = visual
        self.reviewed_fingerprint: str | None = None
        self._viewed_indices: set[int] = {0}
        self.setWindowTitle("Review GPA-aligned meshes")
        self.resize(1420, 930)
        self.setMinimumSize(1000, 720)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "This window renders the exact in-memory transforms from the numerical GPA "
            "preview. By default, every aligned mesh is shown simultaneously as an "
            "equal-weight, high-contrast colored wireframe: coincident silhouettes indicate "
            "matching position, scale, and orientation, while separated colors expose "
            "misalignment immediately. The selected mesh is only drawn slightly thicker. "
            "Enable its shaded surface when you want an individual inspection. Large "
            "surfaces use bounded display proxies here; numerical GPA and atlas computation "
            "remain bound to the complete source meshes. No source or aligned file is "
            "created or changed."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("boundaryText")
        layout.addWidget(explanation)

        controls = QHBoxLayout()
        self.mesh_combo = QComboBox()
        self.mesh_combo.setObjectName("gpaReviewMeshCombo")
        for index, mesh in enumerate(visual.meshes):
            role = "Template" if index == 0 else f"Subject {index}"
            self.mesh_combo.addItem(
                f"{role}: {Path(mesh.path).name}",
                index,
            )
        self.mesh_combo.currentIndexChanged.connect(self._select_mesh)
        self.previous_button = QPushButton("Previous")
        self.previous_button.setObjectName("secondary")
        self.previous_button.clicked.connect(lambda: self._move_mesh(-1))
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("secondary")
        self.next_button.clicked.connect(lambda: self._move_mesh(1))
        self.restart_sequence_button = QPushButton("Review again from first mesh")
        self.restart_sequence_button.setObjectName("secondary")
        self.restart_sequence_button.setToolTip(
            "Explicitly return to mesh 1 after the finite review sequence completed."
        )
        self.restart_sequence_button.clicked.connect(self._restart_sequence)
        self.restart_sequence_button.hide()
        worst_button = QPushButton("Highest residual")
        worst_button.setObjectName("secondary")
        worst_button.setToolTip(
            "Select the specimen with the largest squared landmark residual."
        )
        worst_button.clicked.connect(self._select_highest_residual)
        self.view_combo = QComboBox()
        for label, preset in (
            ("3/4 view", "three-quarter"),
            ("Front", "front"),
            ("Back", "back"),
            ("Left", "left"),
            ("Right", "right"),
            ("Top", "top"),
            ("Bottom", "bottom"),
        ):
            self.view_combo.addItem(label, preset)
        self.view_combo.currentIndexChanged.connect(self._change_view)
        reset_button = QPushButton("Reset view")
        reset_button.setObjectName("secondary")
        reset_button.clicked.connect(self._reset_view)
        controls.addWidget(QLabel("Selected mesh"))
        controls.addWidget(self.mesh_combo, 2)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.restart_sequence_button)
        controls.addWidget(worst_button)
        controls.addWidget(QLabel("View"))
        controls.addWidget(self.view_combo)
        controls.addWidget(reset_button)
        layout.addLayout(controls)

        display_controls = QHBoxLayout()
        self.cohort_overlay_check = QCheckBox(
            "Show all meshes simultaneously (colored overlay)"
        )
        self.cohort_overlay_check.setChecked(True)
        self.cohort_overlay_check.toggled.connect(self._set_cohort_visible)
        self.selected_surface_check = QCheckBox(
            "Show selected shaded surface (individual inspection)"
        )
        self.selected_surface_check.setChecked(False)
        self.selected_surface_check.toggled.connect(self._set_selected_surface_visible)
        self.landmarks_check = QCheckBox(
            "Show selected, cohort, and consensus landmarks"
        )
        self.landmarks_check.setChecked(True)
        self.landmarks_check.toggled.connect(self._set_landmarks_visible)
        self.sampling_label = QLabel(
            f"Display proxies: up to {visual.detail_triangle_budget:,} faces per mesh; "
            f"{visual.total_displayed_edges:,} overlay edges from "
            f"{visual.total_source_triangles:,} full-resolution source faces"
        )
        self.sampling_label.setObjectName("hint")
        display_controls.addWidget(self.cohort_overlay_check)
        display_controls.addWidget(self.selected_surface_check)
        display_controls.addWidget(self.landmarks_check)
        display_controls.addStretch()
        display_controls.addWidget(self.sampling_label)
        layout.addLayout(display_controls)

        self.canvas = GpaAlignmentCanvas3D()
        self.canvas.set_visual(visual)
        self.canvas.set_selected_proxy(0)
        layout.addWidget(self.canvas, 1)

        review_status = QHBoxLayout()
        self.mesh_status_label = QLabel()
        self.mesh_status_label.setWordWrap(True)
        self.mesh_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.inspection_progress_label = QLabel()
        self.inspection_progress_label.setObjectName("gpaReviewProgressLabel")
        self.inspection_progress_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        review_status.addWidget(self.mesh_status_label, 3)
        review_status.addWidget(self.inspection_progress_label, 1)
        layout.addLayout(review_status)

        completion = QHBoxLayout()
        self.review_complete_check = QCheckBox(
            "I visually reviewed the cohort overlay and inspected relevant individual "
            "meshes"
        )
        self.review_complete_check.setObjectName("gpaVisualReviewCompleteCheck")
        self.review_complete_check.toggled.connect(self._update_completion_button)
        close_button = QPushButton("Close without completing review")
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.reject)
        self.complete_button = QPushButton("Complete visual GPA review")
        self.complete_button.setObjectName("primary")
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self._complete_review)
        completion.addWidget(self.review_complete_check, 1)
        completion.addWidget(close_button)
        completion.addWidget(self.complete_button)
        layout.addLayout(completion)
        self._update_mesh_status(0)

    @property
    def viewed_mesh_count(self) -> int:
        return len(self._viewed_indices)

    @Slot(int)
    def _select_mesh(self, combo_index: int) -> None:
        if combo_index < 0:
            return
        index = int(self.mesh_combo.itemData(combo_index))
        self.canvas.set_selected_proxy(index)
        self._viewed_indices.add(index)
        self._update_mesh_status(index)

    def _update_mesh_status(self, index: int) -> None:
        mesh = self.visual.meshes[index]
        residuals = sorted(
            (item.squared_landmark_residual for item in self.visual.meshes),
            reverse=True,
        )
        rank = residuals.index(mesh.squared_landmark_residual) + 1
        self.mesh_status_label.setStyleSheet("")
        self.mesh_status_label.setText(
            f"{Path(mesh.path).name}  |  {mesh.source_format.upper()}  |  "
            f"{mesh.source_point_count:,} points / "
            f"{mesh.source_triangle_count:,} triangles  |  "
            f"squared landmark residual {mesh.squared_landmark_residual:.6g} "
            f"(rank {rank} of {len(residuals)}, highest first)  |  "
            f"GPA scale {mesh.applied_scale:.6g}"
        )
        self.inspection_progress_label.setText(
            f"Mesh {index + 1} of {len(self.visual.meshes)} · unique viewed "
            f"{len(self._viewed_indices)} / {len(self.visual.meshes)}"
            + (
                " · All meshes viewed"
                if len(self._viewed_indices) == len(self.visual.meshes)
                else ""
            )
        )
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index + 1 < len(self.visual.meshes))
        self.next_button.setText(
            "Last mesh reached" if index + 1 == len(self.visual.meshes) else "Next"
        )
        self.restart_sequence_button.setVisible(
            len(self._viewed_indices) == len(self.visual.meshes)
        )

    @Slot()
    def _select_highest_residual(self) -> None:
        index = max(
            range(len(self.visual.meshes)),
            key=lambda item: self.visual.meshes[item].squared_landmark_residual,
        )
        self.mesh_combo.setCurrentIndex(index)

    def _move_mesh(self, offset: int) -> None:
        count = self.mesh_combo.count()
        if not count:
            return
        current = self.mesh_combo.currentIndex()
        destination = max(0, min(count - 1, current + offset))
        if destination != current:
            self.mesh_combo.setCurrentIndex(destination)

    @Slot()
    def _restart_sequence(self) -> None:
        if len(self._viewed_indices) != len(self.visual.meshes):
            return
        self.mesh_combo.setCurrentIndex(0)

    @Slot(int)
    def _change_view(self, _index: int) -> None:
        preset = self.view_combo.currentData()
        if preset:
            self.canvas.set_view_preset(str(preset))

    @Slot()
    def _reset_view(self) -> None:
        self.view_combo.setCurrentIndex(0)
        self.canvas.reset_view()

    @Slot(bool)
    def _set_cohort_visible(self, visible: bool) -> None:
        self.canvas.set_show_cohort(visible)

    @Slot(bool)
    def _set_selected_surface_visible(self, visible: bool) -> None:
        self.canvas.set_show_selected_surface(visible)

    @Slot(bool)
    def _set_landmarks_visible(self, visible: bool) -> None:
        self.canvas.set_show_landmarks(visible)

    @Slot(bool)
    def _update_completion_button(self, checked: bool) -> None:
        self.complete_button.setEnabled(checked)

    @Slot()
    def _complete_review(self) -> None:
        if not self.review_complete_check.isChecked():
            return
        self.reviewed_fingerprint = self.visual.fingerprint
        self.accept()
