"""Aspect-ratio-safe SVG presentation for the desktop result pages."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QWidget


class AspectRatioSvgWidget(QWidget):
    """Render an SVG into an explicitly fitted and centered target rectangle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer(self)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def renderer(self) -> QSvgRenderer:
        """Expose the renderer for the existing validity checks."""

        return self._renderer

    def load(self, filename: str) -> None:
        """Load one verified SVG file and refresh layout geometry."""

        self._renderer.load(filename)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        size = self._renderer.defaultSize()
        return size if size.isValid() and not size.isEmpty() else QSize(1100, 720)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        hint = self.sizeHint()
        width = min(550, hint.width())
        return QSize(width, self.heightForWidth(width))

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt virtual method name
        return max(1, round(width / self._source_aspect_ratio()))

    def fitted_target_rect(self, bounds: QRectF | None = None) -> QRectF:
        """Return centered paint bounds with the exact source aspect ratio."""

        available = QRectF(self.rect()) if bounds is None else QRectF(bounds)
        if available.width() <= 0 or available.height() <= 0:
            return QRectF()
        ratio = self._source_aspect_ratio()
        width = min(available.width(), available.height() * ratio)
        height = width / ratio
        left = available.left() + (available.width() - width) / 2.0
        top = available.top() + (available.height() - height) / 2.0
        return QRectF(left, top, width, height)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt virtual method name
        del event
        if not self._renderer.isValid():
            return
        painter = QPainter(self)
        try:
            self._renderer.render(painter, self.fitted_target_rect())
        finally:
            painter.end()

    def _source_aspect_ratio(self) -> float:
        view_box = self._renderer.viewBoxF()
        if view_box.width() > 0 and view_box.height() > 0:
            return view_box.width() / view_box.height()
        size = self._renderer.defaultSize()
        if size.width() > 0 and size.height() > 0:
            return size.width() / size.height()
        return 1100 / 720
