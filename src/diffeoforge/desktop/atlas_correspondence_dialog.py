"""Inspect one exact material vertex across two saved Deformetrica atlases."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from vtkmodules.vtkCommonCore import reference
from vtkmodules.vtkCommonDataModel import vtkGenericCell, vtkStaticCellLocator

from diffeoforge.analysis.atlas_group_anatomy import _MAX_MESH_BYTES, _template_record
from diffeoforge.atlas_comparison import _review
from diffeoforge.desktop.calibration_comparison_widget import CalibrationComparisonCanvas3D
from diffeoforge.desktop.landmark_3d_widget import InteractiveMeshCanvas3D
from diffeoforge.desktop.mesh_preview import MeshPreviewModel, load_mesh_preview
from diffeoforge.desktop.preview_mesh_loader import PreviewMeshLoader
from diffeoforge.desktop.region_marking_geometry import _cell_locator
from diffeoforge.desktop.result_review import ModernResultReview, verify_result_artifact
from diffeoforge.mesh import sha256_file


@dataclass(frozen=True, eq=False)
class _ProbeSource:
    reviews: tuple[ModernResultReview, ModernResultReview]
    template: MeshPreviewModel
    specimens: tuple[str, ...]
    locator: vtkStaticCellLocator

    def pick_vertex(self, start, end) -> int | None:
        """Snap to an exact vertex of the first intersected original triangle."""
        position, coordinates = [0.0] * 3, [0.0] * 3
        face = reference(0)
        tolerance = 64 * np.finfo(np.float64).eps * max(map(abs, (*start, *end)))
        if not self.locator.IntersectWithLine(
            start, end, tolerance, reference(0.0), position, coordinates,
            reference(0), face, vtkGenericCell(),
        ):
            return None
        corners = np.asarray(self.template.triangles[int(face)])
        points = np.asarray([self.template.vertices[index] for index in corners])
        return int(corners[np.argmin(np.sum((points - position) ** 2, axis=1))])


def _checked_preview(path, size, digest):
    if not 0 < size <= _MAX_MESH_BYTES or path.stat().st_size != size:
        raise ValueError("A bound surface changed size or exceeds the probe's mesh-size limit.")
    preview = load_mesh_preview(path)
    if preview.sha256 != digest or preview.geometry_is_proxy:
        raise ValueError("A bound surface no longer has its verified full geometry.")
    return preview


def _verify_template_pair(reviews):
    first, second = map(_template_record, reviews)
    if first[1:] != second[1:]:
        raise ValueError("The atlases have different verified starting-template bytes.")
    for path, size, digest in (first, second):
        if (
            not 0 < size <= _MAX_MESH_BYTES
            or path.stat().st_size != size
            or sha256_file(path) != digest
        ):
            raise ValueError("A staged starting template changed or exceeds the mesh-size limit.")
    return first


def _load_probe(first: Path, second: Path) -> _ProbeSource:
    reviews = (
        _review(first, create_pca_if_missing=False),
        _review(second, create_pca_if_missing=False),
    )
    if reviews[0].run_directory == reviews[1].run_directory:
        raise ValueError("Choose two different completed atlases.")
    template = _checked_preview(*_verify_template_pair(reviews))
    names = [{item.subject_name for item in review.registration_qc} for review in reviews]
    if any(len(ids) != len(review.registration_qc) for ids, review in zip(names, reviews,
                                                                          strict=True)):
        raise ValueError("The saved atlas specimen identities are ambiguous.")
    specimens = tuple(sorted(names[0] & names[1], key=lambda name: (name.casefold(), name)))
    if not specimens:
        raise ValueError("The two verified atlases have no shared registration-QC specimens.")
    locator = _cell_locator(
        np.asarray(template.vertices, dtype=np.float64),
        np.asarray(template.triangles, dtype=np.int64),
    )
    return _ProbeSource(reviews, template, specimens, locator)


def _load_specimen(source: _ProbeSource, specimen: str):
    if specimen not in source.specimens:
        raise ValueError("Choose a specimen with verified reconstructions in both atlases.")
    _verify_template_pair(source.reviews)
    selections = tuple(review.registration_qc_item(specimen) for review in source.reviews)
    originals = tuple(
        review.artifact(item.original_artifact_key)
        for review, item in zip(source.reviews, selections, strict=True)
    )
    if (originals[0].bytes, originals[0].sha256) != (originals[1].bytes, originals[1].sha256):
        raise ValueError("The selected specimen has different aligned original bytes.")

    def artifact(review, key):
        record = review.artifact(key)
        if record.kind != "vtk" or not 0 < record.bytes <= _MAX_MESH_BYTES:
            raise ValueError("A selected registration artifact is not a supported VTK surface.")
        return verify_result_artifact(review, key), record.bytes, record.sha256

    original_a, _original_b = (
        artifact(review, item.original_artifact_key)
        for review, item in zip(source.reviews, selections, strict=True)
    )
    original = _checked_preview(*original_a)
    reconstructions = tuple(
        _checked_preview(*artifact(review, item.reconstruction_artifact_key))
        for review, item in zip(source.reviews, selections, strict=True)
    )
    if any(
        item.point_count != source.template.point_count
        or tuple(item.triangles) != tuple(source.template.triangles)
        for item in reconstructions
    ):
        raise ValueError("A reconstruction differs from the shared template's ordered topology.")
    return original, *reconstructions


class AtlasCorrespondenceDialog(QDialog):
    """Pick a template vertex and inspect where both reconstructions place it."""

    def __init__(self, first: Path, second: Path, parent=None) -> None:
        super().__init__(parent)
        self._source: _ProbeSource | None = None
        self._pair: tuple[MeshPreviewModel, ...] | None = None
        self._picked_vertex: int | None = None
        self._target_landmark: tuple[float, float, float] | None = None
        self.setWindowTitle("Trace a point across atlases")
        self.resize(1100, 620)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Choose a shared specimen and click the starting template. The closest corner "
            "of the hit triangle is traced by the same vertex index in both reconstructions. "
            "The marker shows model correspondence. Anatomical homology requires independent "
            "evidence."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        choices = QHBoxLayout()
        self.specimens = QComboBox()
        self.specimens.setPlaceholderText("Choose a shared specimen")
        self.specimens.setAccessibleName("Shared specimen")
        self.specimens.setEnabled(False)
        self.vertex = QSpinBox()
        self.vertex.setRange(-1, -1)
        self.vertex.setSpecialValueText("Unselected")
        self.vertex.setAccessibleName("Template vertex index")
        self.vertex.setEnabled(False)
        choices.addWidget(QLabel("Specimen"))
        choices.addWidget(self.specimens, 1)
        choices.addWidget(QLabel("Vertex index (zero-based)"))
        choices.addWidget(self.vertex)
        layout.addLayout(choices)

        target = QHBoxLayout()
        target.addWidget(QLabel("Optional independent landmark XYZ"))
        self.landmark_input = QLineEdit()
        self.landmark_input.setAccessibleName("Independent landmark in aligned XYZ coordinates")
        self.landmark_input.setPlaceholderText("Shared aligned units, e.g. 1.25 -0.3 0.8")
        self.landmark_input.setToolTip(
            "Use coordinates measured independently on this specimen in the same aligned "
            "frame as the orange original. Coordinates are used as entered."
        )
        self.landmark_input.setEnabled(False)
        self.landmark_apply = QPushButton("Use aligned XYZ")
        self.landmark_apply.setEnabled(False)
        self.landmark_clear = QPushButton("Clear landmark")
        self.landmark_clear.setEnabled(False)
        target.addWidget(self.landmark_input, 1)
        target.addWidget(self.landmark_apply)
        target.addWidget(self.landmark_clear)
        layout.addLayout(target)

        self.template = InteractiveMeshCanvas3D(progressive_navigation=True)
        self.template.setAccessibleName("Shared starting template for exact vertex selection")
        self.template.pick_instruction = "Click: select a material vertex"
        self.template.original_detail.setToolTip("Load more detail when picking a small feature.")
        self.template.set_picking_enabled(False)
        self.left = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.right = CalibrationComparisonCanvas3D(show_inspection_hints=False)
        self.left.cameraChanged.connect(self.right.set_linked_camera)
        self.right.cameraChanged.connect(self.left.set_linked_camera)
        panels = QHBoxLayout()
        for name, canvas in (
            ("Shared starting template", self.template),
            ("Atlas A · " + first.name, self.left),
            ("Atlas B · " + second.name, self.right),
        ):
            panel = QVBoxLayout()
            title = QLabel(name)
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            panel.addWidget(title)
            canvas.setMinimumHeight(300)
            panel.addWidget(canvas, 1)
            panels.addLayout(panel, 1)
        layout.addLayout(panels, 1)
        self.status = QLabel("Verifying both saved atlases and their starting template…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.landmark_status = QLabel()
        self.landmark_status.setWordWrap(True)
        self.landmark_status.setTextFormat(Qt.TextFormat.PlainText)
        self.landmark_status.hide()
        layout.addWidget(self.landmark_status)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

        self._loader = PreviewMeshLoader(self)
        self._loader.loaded.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self.finished.connect(self._loader.cancel)
        self.template.surfacePointPicked.connect(self._use_picked_vertex)
        self.vertex.valueChanged.connect(self._update_marker)
        self.specimens.currentTextChanged.connect(self._select_specimen)
        self.landmark_input.textChanged.connect(self._clear_target)
        self.landmark_input.returnPressed.connect(self._use_target)
        self.landmark_apply.clicked.connect(self._use_target)
        self.landmark_clear.clicked.connect(self.landmark_input.clear)
        self._loader.request_operation(("source", None), lambda: _load_probe(first, second))

    @Slot(object, object)
    def _loaded(self, key, value):
        if key[0] == "source":
            self._source = value
            self.template.set_model(value.template, surface_picker=self._pick)
            self.template.set_picking_enabled(True)
            self.vertex.setRange(-1, value.template.point_count - 1)
            self.vertex.setEnabled(True)
            self.specimens.blockSignals(True)
            self.specimens.addItems(value.specimens)
            self.specimens.setCurrentIndex(-1)
            self.specimens.blockSignals(False)
            self.specimens.setEnabled(True)
            self.status.setText("Select a specimen to show its two saved reconstructions.")
        elif self.specimens.currentText() == key[1]:
            self._pair = value
            original, first, second = value
            self.left.set_models(original, first)
            self.right.set_models(original, second)
            bounds = np.asarray([model.bounds for model in value]).reshape(3, 3, 2)
            low, high = bounds[:, :, 0].min(axis=0), bounds[:, :, 1].max(axis=0)
            for canvas in (self.left, self.right):
                canvas.set_comparison_extent((low + high) / 2, float(np.max(high - low)))
            self.right.set_linked_camera(self.left.camera_state())
            self.landmark_input.setEnabled(True)
            self._update_marker()

    @Slot(object, str)
    def _failed(self, key, message):
        if key[0] == "source" or self.specimens.currentText() == key[1]:
            self.status.setText(f"Correspondence probe unavailable. {message}")

    @Slot(str)
    def _select_specimen(self, specimen):
        self._pair = None
        self.landmark_input.setEnabled(False)
        self.landmark_input.clear()
        self._clear_target()
        for canvas in (self.left, self.right):
            canvas.clear()
            canvas.set_inspection_markers({})
        source = self._source
        if source is not None and specimen:
            self.status.setText("Verifying the specimen and both reconstructions…")
            self._loader.request_operation(
                ("specimen", specimen), lambda: _load_specimen(source, specimen),
            )
        else:
            self._loader.cancel()
            self.status.setText("Choose a specimen to load both reconstructions.")

    def _pick(self, start, end):
        self._picked_vertex = self._source.pick_vertex(start, end)
        if self._picked_vertex is None:
            return None
        return self._source.template.vertices[self._picked_vertex]

    @Slot(object)
    def _use_picked_vertex(self, _point):
        if self._picked_vertex is not None:
            self.vertex.setValue(self._picked_vertex)

    @Slot()
    def _clear_target(self):
        had_target = self._target_landmark is not None
        self._target_landmark = None
        self.landmark_status.clear()
        self.landmark_status.hide()
        has_input = bool(self._pair is not None and self.landmark_input.text().strip())
        self.landmark_apply.setEnabled(has_input)
        self.landmark_clear.setEnabled(has_input)
        if self._pair is not None and had_target:
            self._update_marker()

    @Slot()
    def _use_target(self):
        if self._pair is None:
            return
        fields = self.landmark_input.text().replace(",", " ").split()
        try:
            point = tuple(float(field) for field in fields)
        except ValueError:
            point = ()
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            self.landmark_status.setText(
                "Enter three finite XYZ values in the shared aligned frame."
            )
            self.landmark_status.show()
            return
        self._target_landmark = point
        self._update_marker()

    @Slot()
    def _update_marker(self):
        index = self.vertex.value()
        label = str(index)
        picked = index >= 0
        self.template.set_markers(
            {label: self._source.template.vertices[index]} if picked else {},
        )
        if self._pair is None:
            return
        original, first, second = self._pair
        target = self._target_landmark
        # Keep markers outside the original surface's viewing extent off the canvas.
        limits = tuple(zip(original.bounds[::2], original.bounds[1::2], strict=True))
        margin = max(high - low for low, high in limits)
        show_target = target is not None and all(
            low - margin <= xyz <= high + margin
            for xyz, (low, high) in zip(target, limits, strict=True)
        )
        for canvas, model in ((self.left, first), (self.right, second)):
            markers = {label: model.vertices[index]} if picked else {}
            if show_target:
                markers["Landmark"] = target
            canvas.set_inspection_markers(markers)
        if picked:
            gap = math.dist(first.vertices[index], second.vertices[index])
            self.status.setText(
                f"Vertex {index} · endpoint distance {gap:.6g} in aligned coordinate units. "
                "Orange shows the shared original. Blue shows the reconstruction."
            )
        else:
            self.status.setText("Click the template or enter a vertex index.")
        if target is not None:
            if picked:
                a, b = (math.dist(model.vertices[index], target) for model in (first, second))
                message = (
                    f"Distances to entered landmark · Atlas A {a:.6g} · Atlas B {b:.6g} "
                    "(aligned units)."
                    if math.isfinite(a) and math.isfinite(b) else
                    "Distances to this landmark exceed the numerical range."
                )
            else:
                message = "Landmark set. Select a template vertex to compare endpoint distances."
            if not show_target:
                message += " The landmark is outside the specimen view."
            self.landmark_status.setText(message)
            self.landmark_status.show()
