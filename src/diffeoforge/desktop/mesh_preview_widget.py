"""Native Qt wireframe canvas for one immutable template preview model."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QCheckBox, QWidget

from diffeoforge.desktop.display_proxy import DEFAULT_DISPLAY_FACES
from diffeoforge.desktop.mesh_preview import (
    DEFAULT_EDGE_BUDGET,
    MeshPreviewModel,
    PreviewPlane,
)


class MeshPreviewCanvas(QWidget):
    """Draw a bounded deterministic wireframe projection with QPainter."""

    vertexPicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: MeshPreviewModel | None = None
        self._plane: PreviewPlane = "xy"
        self._picking_enabled = False
        self._markers: dict[str, int] = {}
        self._display_model: MeshPreviewModel | None = None
        self.original_detail = QCheckBox("Original vertices (slower)", self)
        self.original_detail.move(10, 10)
        self.original_detail.toggled.connect(self.update)
        self.setMinimumHeight(280)
        self.setObjectName("meshPreviewCanvas")

    def set_model(self, model: MeshPreviewModel | None) -> None:
        self._model = model
        self.original_detail.setChecked(False)
        self.original_detail.setEnabled(model is not None and not model.geometry_is_proxy)
        self._display_model = model
        if model is not None and model.display_proxy is not None:
            proxy = model.display_proxy
            self._display_model = MeshPreviewModel(
                model.path,
                model.sha256,
                tuple(tuple(float(v) for v in row) for row in proxy.vertices),
                tuple(tuple(int(v) for v in row) for row in proxy.triangles),
                tuple(tuple(int(v) for v in row) for row in proxy.edges),
                model.bounds,
                geometry_is_proxy=proxy.reduced,
            )
        elif model is not None and model.triangle_count > DEFAULT_DISPLAY_FACES:
            self._display_model = None
        self.update()

    def set_plane(self, plane: PreviewPlane) -> None:
        if plane not in {"xy", "xz", "yz"}:
            raise ValueError(f"Unsupported preview plane: {plane!r}")
        self._plane = plane
        self.update()

    def set_picking_enabled(self, enabled: bool) -> None:
        self._picking_enabled = bool(enabled)
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def set_markers(self, markers: dict[str, int]) -> None:
        self._markers = dict(markers)
        self.update()

    def _projection_geometry(self, *, original: bool = False):
        if self._model is None:
            return None
        model = self._model if original or self.original_detail.isChecked() else self._display_model
        if model is None:
            return None
        budget = model.edge_count if self.original_detail.isChecked() else DEFAULT_EDGE_BUDGET
        projection = model.project(self._plane, edge_budget=max(1, budget))
        margin = 18.0
        available_width = max(1.0, self.width() - 2.0 * margin)
        available_height = max(1.0, self.height() - 2.0 * margin)
        size = min(available_width, available_height)
        left = (self.width() - size) / 2.0
        top = (self.height() - size) / 2.0

        def point(value: tuple[float, float]) -> QPointF:
            return QPointF(
                left + (value[0] + 1.0) * 0.5 * size,
                top + (value[1] + 1.0) * 0.5 * size,
            )

        return projection, point

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self._picking_enabled or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._model is None or self._model.geometry_is_proxy:
            return
        if (
            self._model.triangle_count > DEFAULT_DISPLAY_FACES
            and not self.original_detail.isChecked()
        ):
            return
        geometry = self._projection_geometry()
        if geometry is None:
            return
        projection, point = geometry
        position = event.position()
        nearest: tuple[float, int] | None = None
        for local_index, source_index in enumerate(projection.source_vertex_indices):
            rendered = point(projection.points[local_index])
            distance = (rendered.x() - position.x()) ** 2 + (rendered.y() - position.y()) ** 2
            if nearest is None or distance < nearest[0]:
                nearest = (distance, source_index)
        if nearest is not None and nearest[0] <= 18.0**2:
            self.vertexPicked.emit(nearest[1])

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._model is None or self._projection_geometry() is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(18, 18, -18, -18),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                (
                    "Display proxy unavailable. Select Original vertices for a slower inspection."
                    if self._model is not None
                    else "Template preview has not been loaded."
                ),
            )
            painter.end()
            return

        projection, point = self._projection_geometry()

        path = QPainterPath()
        for start, end in projection.edges:
            path.moveTo(point(projection.points[start]))
            path.lineTo(point(projection.points[end]))
        painter.setPen(QPen(QColor("#167c6b"), 0.8))
        painter.drawPath(path)
        # Marker indexes always refer to the original, never clustered vertices.
        if self._markers:
            projection, point = self._projection_geometry(original=True)
        local_by_source = {
            source: local for local, source in enumerate(projection.source_vertex_indices)
        }
        for marker_number, (label, source_index) in enumerate(self._markers.items(), start=1):
            local_index = local_by_source.get(source_index)
            if local_index is None:
                continue
            rendered = point(projection.points[local_index])
            painter.setPen(QPen(QColor("#ffffff"), 1.2))
            painter.setBrush(QColor("#d9481c"))
            painter.drawEllipse(rendered, 6.0, 6.0)
            painter.setPen(QPen(QColor("#7a240b"), 1.0))
            painter.drawText(rendered + QPointF(8.0, -8.0), f"{marker_number}: {label}")
        if (
            not self.original_detail.isChecked()
            and self._model.triangle_count > DEFAULT_DISPLAY_FACES
        ):
            painter.setPen(QColor("#705419"))
            painter.drawText(
                10, self.height() - 10, "Reduced display; original-vertex picking disabled."
            )
        painter.end()
