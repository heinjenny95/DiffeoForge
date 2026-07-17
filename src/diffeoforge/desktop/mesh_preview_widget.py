"""Native Qt wireframe canvas for one immutable template preview model."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from diffeoforge.desktop.mesh_preview import (
    DEFAULT_EDGE_BUDGET,
    MeshPreviewModel,
    PreviewPlane,
)


class MeshPreviewCanvas(QWidget):
    """Draw a bounded deterministic wireframe projection with QPainter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: MeshPreviewModel | None = None
        self._plane: PreviewPlane = "xy"
        self.setMinimumHeight(280)
        self.setObjectName("meshPreviewCanvas")

    def set_model(self, model: MeshPreviewModel | None) -> None:
        self._model = model
        self.update()

    def set_plane(self, plane: PreviewPlane) -> None:
        if plane not in {"xy", "xz", "yz"}:
            raise ValueError(f"Unsupported preview plane: {plane!r}")
        self._plane = plane
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f9f9"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._model is None:
            painter.setPen(QColor("#64777c"))
            painter.drawText(
                self.rect().adjusted(18, 18, -18, -18),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Template-Vorschau noch nicht geladen.",
            )
            painter.end()
            return

        projection = self._model.project(
            self._plane,
            edge_budget=DEFAULT_EDGE_BUDGET,
        )
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

        path = QPainterPath()
        for start, end in projection.edges:
            path.moveTo(point(projection.points[start]))
            path.lineTo(point(projection.points[end]))
        painter.setPen(QPen(QColor("#167c6b"), 0.8))
        painter.drawPath(path)
        painter.end()
