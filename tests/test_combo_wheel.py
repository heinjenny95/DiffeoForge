"""Closed selectors do not mutate values while users scroll dialog panels."""

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QScrollArea, QVBoxLayout, QWidget

from diffeoforge.desktop.combo_wheel import install_combo_wheel_guard


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert install_combo_wheel_guard(application) is install_combo_wheel_guard(application)
    return application


def _wheel(widget, *, pixel=False):
    QCoreApplication.sendEvent(widget, QWheelEvent(
        QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))),
        QPoint(0, -25) if pixel else QPoint(), QPoint() if pixel else QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False))


@pytest.mark.parametrize("editable", [False, True])
@pytest.mark.parametrize("pixel", [False, True])
def test_later_created_dialog_combo_scrolls_parent_even_when_focused(app, editable, pixel):
    dialog = QDialog()
    body = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    content.setMinimumHeight(1400)
    layout = QVBoxLayout(content)
    combo = QComboBox()
    combo.setEditable(editable)
    combo.addItems(["Current", "Varifold", "Another"])
    combo.setCurrentIndex(1)
    layout.addWidget(combo)
    layout.addStretch()
    scroll.setWidget(content)
    body.addWidget(scroll)
    dialog.resize(400, 240)
    dialog.show()
    combo.setFocus()
    app.processEvents()
    try:
        bar = scroll.verticalScrollBar()
        assert bar.maximum() > 0
        _wheel(combo.lineEdit() if editable else combo, pixel=pixel)
        assert combo.currentIndex() == 1 and combo.currentText() == "Varifold"
        assert bar.value() > 0
    finally:
        dialog.close()
        app.processEvents()


def test_no_scroll_parent_still_protects_closed_selection_and_keyboard_works(app):
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    combo = QComboBox()
    combo.addItems(["One", "Two", "Three"])
    combo.setCurrentIndex(1)
    layout.addWidget(combo)
    dialog.show()
    app.processEvents()
    try:
        _wheel(combo)
        assert combo.currentIndex() == 1
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert combo.currentIndex() == 2
        QTest.keyClick(combo, Qt.Key.Key_Up)
        assert combo.currentIndex() == 1
    finally:
        dialog.close()
        app.processEvents()


def test_open_popup_keeps_wheel_scrolling_and_click_selection(app):
    combo = QComboBox()
    combo.addItems([f"Item {i}" for i in range(60)])
    combo.setMaxVisibleItems(6)
    combo.show()
    combo.showPopup()
    app.processEvents()
    try:
        view = combo.view()
        assert view.isVisible()
        view.verticalScrollBar().setValue(0)
        _wheel(view.viewport())
        app.processEvents()
        assert view.verticalScrollBar().value() > 0
        index = view.indexAt(QPoint(5, 5))
        assert index.isValid()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         pos=view.visualRect(index).center())
        assert combo.currentIndex() == index.row()
    finally:
        combo.hidePopup()
        combo.close()
        app.processEvents()
