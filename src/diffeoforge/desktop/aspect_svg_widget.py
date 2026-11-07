"""Aspect-ratio-safe SVG presentation for the desktop result pages."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget


@dataclass(frozen=True)
class _SvgHoverPoint:
    x: float
    y: float
    tooltip: str


class AspectRatioSvgWidget(QWidget):
    """Render an SVG into an explicitly fitted and centered target rectangle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer(self)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMouseTracking(True)
        self._hover_points: tuple[_SvgHoverPoint, ...] = ()
        self._visible_tooltip: str | None = None

    def renderer(self) -> QSvgRenderer:
        """Expose the renderer for the existing validity checks."""

        return self._renderer

    def load(self, filename: str) -> None:
        """Load one verified SVG file and refresh layout geometry."""

        self._renderer.load(filename)
        self._hover_points = self._read_hover_points(Path(filename))
        self._visible_tooltip = None
        self.updateGeometry()
        self.update()

    @property
    def hover_point_count(self) -> int:
        """Return the number of embedded subject points available for hover."""

        return len(self._hover_points)

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

    def hover_tooltip_at(self, position: QPointF, *, radius: float = 12.0) -> str | None:
        """Return the nearest subject tooltip at one widget-space position."""

        if not self._hover_points or not self._renderer.isValid():
            return None
        target = self.fitted_target_rect()
        view_box = self._renderer.viewBoxF()
        if (
            target.width() <= 0
            or target.height() <= 0
            or view_box.width() <= 0
            or view_box.height() <= 0
        ):
            return None
        best: tuple[float, str] | None = None
        for point in self._hover_points:
            widget_x = target.left() + (
                (point.x - view_box.left()) / view_box.width()
            ) * target.width()
            widget_y = target.top() + (
                (point.y - view_box.top()) / view_box.height()
            ) * target.height()
            distance = math.hypot(position.x() - widget_x, position.y() - widget_y)
            if distance <= radius and (best is None or distance < best[0]):
                best = (distance, point.tooltip)
        return None if best is None else best[1]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt virtual method name
        tooltip = self.hover_tooltip_at(event.position())
        if tooltip is None:
            if self._visible_tooltip is not None:
                QToolTip.hideText()
                self._visible_tooltip = None
        elif tooltip != self._visible_tooltip:
            QToolTip.showText(event.globalPosition().toPoint(), tooltip, self)
            self._visible_tooltip = tooltip
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt virtual method name
        QToolTip.hideText()
        self._visible_tooltip = None
        super().leaveEvent(event)

    def _source_aspect_ratio(self) -> float:
        view_box = self._renderer.viewBoxF()
        if view_box.width() > 0 and view_box.height() > 0:
            return view_box.width() / view_box.height()
        size = self._renderer.defaultSize()
        if size.width() > 0 and size.height() > 0:
            return size.width() / size.height()
        return 1100 / 720

    @staticmethod
    def _read_hover_points(path: Path) -> tuple[_SvgHoverPoint, ...]:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return ()
        points: list[_SvgHoverPoint] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "circle":
                continue
            label = element.attrib.get("data-subject-label")
            if not label:
                continue
            try:
                x = float(element.attrib["cx"])
                y = float(element.attrib["cy"])
            except (KeyError, ValueError):
                continue
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            tooltip_lines = [label]
            x_axis = element.attrib.get("data-x-axis")
            x_score = element.attrib.get("data-x-score")
            y_axis = element.attrib.get("data-y-axis")
            y_score = element.attrib.get("data-y-score")
            if x_axis and x_score:
                tooltip_lines.append(f"{x_axis}: {x_score}")
            if y_axis and y_score:
                tooltip_lines.append(f"{y_axis}: {y_score}")
            points.append(_SvgHoverPoint(x=x, y=y, tooltip="\n".join(tooltip_lines)))
        return tuple(points)
