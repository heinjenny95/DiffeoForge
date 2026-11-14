"""Lightweight observer of logged reference objectives; never controls the optimizer."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

MAX_LIVE_SAMPLES = 5000
_OBJECTIVE_COLOR = "#147d70"
_ATTACHMENT_COLOR = "#c47d16"
_REGULARITY_COLOR = "#7057a3"


@dataclass(frozen=True)
class LiveOptimizerSample:
    iteration: int
    objective: float
    attachment: float
    regularity: float


class LiveOptimizerPlot(QWidget):
    """Show only complete, finite, increasing-iteration worker observations."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveOptimizerPlot")
        self._samples: deque[LiveOptimizerSample] = deque(maxlen=MAX_LIVE_SAMPLES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        header = QHBoxLayout()
        title = QLabel("Live optimizer convergence")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        legend = QHBoxLayout()
        objective = QLabel("Objective")
        objective.setStyleSheet(f"color: {_OBJECTIVE_COLOR};")
        legend.addWidget(objective)
        self.attachment_checkbox = QCheckBox("Attachment")
        self.attachment_checkbox.setStyleSheet(f"color: {_ATTACHMENT_COLOR};")
        self.regularity_checkbox = QCheckBox("Regularity")
        self.regularity_checkbox.setStyleSheet(f"color: {_REGULARITY_COLOR};")
        self.regularity_checkbox.setToolTip("Shown below on its own vertical scale.")
        legend.addWidget(self.attachment_checkbox)
        legend.addWidget(self.regularity_checkbox)
        legend.addStretch()
        layout.addLayout(legend)
        self.canvas = _OptimizerCanvas(self)
        layout.addWidget(self.canvas)
        self.status_label = QLabel("Waiting for the first logged iteration.")
        self.status_label.setObjectName("reviewDetail")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setToolTip(
            "Observed values from this session, with automatically scaled axes. "
            "Anatomical fit still needs visual review. Only the latest 5,000 "
            "observations are drawn; the full run log is unchanged."
        )
        self.attachment_checkbox.toggled.connect(self.canvas.update)
        self.regularity_checkbox.toggled.connect(self._change_panels)

    @property
    def samples(self) -> tuple[LiveOptimizerSample, ...]:
        return tuple(self._samples)

    def clear(self) -> None:
        self._samples.clear()
        self.status_label.setText("Waiting for the first logged iteration.")
        self.canvas.update()

    def add_sample(
        self, iteration: int, objective: float, attachment: float, regularity: float
    ) -> bool:
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
            return False
        values = (objective, attachment, regularity)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            return False
        if self._samples and iteration <= self._samples[-1].iteration:
            return False
        self._samples.append(LiveOptimizerSample(iteration, *map(float, values)))
        first = self._samples[0].iteration
        self.status_label.setText(
            f"Observed iterations {first}–{iteration} · latest objective {objective:.6g}"
        )
        self.canvas.update()
        return True

    def _change_panels(self, enabled: bool) -> None:
        self.canvas.setFixedHeight(360 if enabled else 230)
        self.canvas.update()


class _OptimizerCanvas(QWidget):
    def __init__(self, plot: LiveOptimizerPlot) -> None:
        super().__init__(plot)
        self.plot = plot
        self.setMinimumWidth(260)
        self.setFixedHeight(230)

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        samples = self.plot.samples
        if not samples:
            painter.setPen(QColor("#60747a"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for logged objective values"
            )
            return
        separate = self.plot.regularity_checkbox.isChecked()
        main_height = 210 if separate else self.height()
        series = [("objective", _OBJECTIVE_COLOR, Qt.PenStyle.SolidLine)]
        if self.plot.attachment_checkbox.isChecked():
            series.append(("attachment", _ATTACHMENT_COLOR, Qt.PenStyle.DashLine))
        self._draw_panel(
            painter, QRectF(0, 0, self.width(), main_height), "Objective / log-likelihood", series
        )
        if separate:
            self._draw_panel(
                painter,
                QRectF(0, main_height, self.width(), self.height() - main_height),
                "Regularity · separate scale",
                [("regularity", _REGULARITY_COLOR, Qt.PenStyle.SolidLine)],
            )

    def _draw_panel(
        self,
        painter: QPainter,
        bounds: QRectF,
        title: str,
        series: list[tuple[str, str, Qt.PenStyle]],
    ) -> None:
        samples = self.plot.samples
        chart = bounds.adjusted(108, 28, -20, -38)
        values = [getattr(sample, field) for field, _, _ in series for sample in samples]
        # Normalize first: finite values at opposite floating-point extremes must
        # not overflow subtraction. This also handles flat and zero histories.
        scale = max(max(abs(value) for value in values), 1.0)
        lower, upper = min(values) / scale, max(values) / scale
        padding = max((upper - lower) * 0.06, 0.000001)
        lower, upper = lower - padding, upper + padding
        first, last = samples[0].iteration, samples[-1].iteration
        x_span = max(last - first, 1)
        painter.setPen(QColor("#344e55"))
        painter.drawText(QPointF(chart.left(), bounds.top() + 17), title)
        for tick in range(5):
            fraction = tick / 4
            y = chart.bottom() - fraction * chart.height()
            painter.setPen(QPen(QColor("#e1e9eb"), 1))
            painter.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            value = (lower + fraction * (upper - lower)) * scale
            label = f"{value:.4g}" if math.isfinite(value) else ""
            painter.setPen(QColor("#60747a"))
            painter.drawText(
                QRectF(bounds.left() + 4, y - 9, 96, 18), Qt.AlignmentFlag.AlignRight, label
            )
        x_ticks = min(x_span, 4)
        for tick in ([0] if first == last else range(x_ticks + 1)):
            iteration = first + round(x_span * tick / x_ticks)
            x = chart.left() + (iteration - first) / x_span * chart.width()
            painter.drawText(
                QRectF(x - 27, chart.bottom() + 4, 54, 18),
                Qt.AlignmentFlag.AlignCenter,
                str(iteration),
            )
        painter.drawText(
            QRectF(chart.left(), bounds.bottom() - 18, chart.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            "Iteration",
        )
        painter.save()
        painter.setClipRect(chart.adjusted(-4, -4, 4, 4))
        for field, color, style in series:
            points = QPolygonF(
                [
                    QPointF(
                        chart.left() + (sample.iteration - first) / x_span * chart.width(),
                        chart.bottom()
                        - (getattr(sample, field) / scale - lower)
                        / (upper - lower)
                        * chart.height(),
                    )
                    for sample in samples
                ]
            )
            painter.setPen(QPen(QColor(color), 2, style))
            painter.drawPolyline(points)
            painter.setBrush(QColor(color))
            painter.drawEllipse(points[-1], 3, 3)
        painter.restore()
