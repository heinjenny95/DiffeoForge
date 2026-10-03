from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication, QLabel

from diffeoforge.desktop.aspect_svg_widget import AspectRatioSvgWidget


def test_svg_widget_fits_wide_and_tall_bounds_without_distortion(tmp_path) -> None:
    application = QApplication.instance() or QApplication(["aspect-svg-widget-test"])
    svg = tmp_path / "plot.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="720" '
        'viewBox="0 0 1100 720"><rect width="1100" height="720"/></svg>',
        encoding="utf-8",
    )
    widget = AspectRatioSvgWidget()
    widget.load(str(svg))

    wide = widget.fitted_target_rect(QRectF(0, 0, 2000, 700))
    tall = widget.fitted_target_rect(QRectF(0, 0, 500, 900))
    expected_ratio = 1100 / 720

    assert widget.renderer().isValid()
    assert wide.width() / wide.height() == pytest.approx(expected_ratio)
    assert wide.height() == pytest.approx(700)
    assert wide.left() > 0
    assert tall.width() / tall.height() == pytest.approx(expected_ratio)
    assert tall.width() == pytest.approx(500)
    assert tall.top() > 0
    assert widget.heightForWidth(1100) == 720
    application.processEvents()


def test_svg_widget_exposes_temporary_subject_hover_without_permanent_labels(
    tmp_path,
) -> None:
    application = QApplication.instance() or QApplication(["aspect-svg-hover-test"])
    svg = tmp_path / "scores.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600" '
        'viewBox="0 0 900 600">'
        '<circle cx="450" cy="300" r="4.5" data-subject-label="Coxa_07" '
        'data-x-axis="PC1" data-x-score="-0.125" '
        'data-y-axis="PC2" data-y-score="0.375"><title>Coxa_07</title></circle>'
        "</svg>",
        encoding="utf-8",
    )
    widget = AspectRatioSvgWidget()
    widget.resize(900, 600)
    widget.load(str(svg))

    assert widget.hover_point_count == 1
    assert widget.hover_tooltip_at(QPointF(450, 300)) == (
        "Coxa_07\nPC1: -0.125\nPC2: 0.375"
    )
    assert widget.hover_tooltip_at(QPointF(100, 100)) is None
    assert widget.findChildren(QLabel) == []
    application.processEvents()
