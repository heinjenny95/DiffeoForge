"""Saved application appearance, independent of scientific display colors."""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QVBoxLayout,
)


@dataclass(frozen=True)
class Appearance:
    mode: str = "light"
    accent: str = "#167c6b"

    def __post_init__(self):
        if self.mode not in {"light", "dark"}:
            raise ValueError("Choose light or dark appearance")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.accent):
            raise ValueError("Accent must be a six-digit RGB color")


def contrast_text(color: QColor) -> str:
    def linear(value):
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = sum(
        weight * linear(value)
        for weight, value in zip(
            (0.2126, 0.7152, 0.0722), (color.redF(), color.greenF(), color.blueF()), strict=True
        )
    )
    return "#000000" if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else "#ffffff"


def _contrast(first: QColor, second: QColor) -> float:
    def luminance(color):
        values = (color.redF(), color.greenF(), color.blueF())
        return sum(
            weight * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
            for weight, v in zip((0.2126, 0.7152, 0.0722), values, strict=True)
        )

    left, right = sorted((luminance(first), luminance(second)))
    return (right + 0.05) / (left + 0.05)


def readable_accent(accent: QColor, dark: bool) -> QColor:
    color = QColor(accent)
    hue, saturation, lightness, alpha = color.getHslF()
    background = QColor("#202832" if dark else "#ffffff")
    for _ in range(101):
        color.setHslF(hue, saturation, lightness, alpha)
        if _contrast(color, background) >= 4.5:
            return color
        lightness = min(1.0, lightness + 0.01) if dark else max(0.0, lightness - 0.01)
    return QColor("#ffffff" if dark else "#000000")


def _mix(a: QColor, b: str, fraction: float) -> str:
    other = QColor(b)
    return QColor(
        *(
            round(x * (1 - fraction) + y * fraction)
            for x, y in zip(a.getRgb()[:3], other.getRgb()[:3], strict=True)
        )
    ).name()


def themed_style(source: str, appearance: Appearance) -> str:
    accent = QColor(appearance.accent)
    dark = appearance.mode == "dark"
    # Text links must remain legible even for very pale or near-black accents.
    link = readable_accent(accent, dark)
    mapping = {
        "#167c6b": link.name(),
        "#0f5f52": link.name(),
        "#268f7a": accent.name(),
        "#116858": _mix(accent, "#000000", 0.18),
        "#54c6a1": accent.name(),
        "#123b3a": _mix(accent, "#000000", 0.65),
        "#0b302f": contrast_text(accent),
        "#1b4b49": _mix(accent, "#000000", 0.45),
        "#e8f4f0": _mix(accent, "#1d242b" if dark else "#ffffff", 0.92),
        "#eaf7f4": _mix(accent, "#1d242b" if dark else "#ffffff", 0.93),
        "#b7dcd2": _mix(accent, "#39454f" if dark else "#ffffff", 0.65),
        "#9bd5c8": _mix(accent, "#39454f" if dark else "#ffffff", 0.55),
        "#245b52": "#d5e8e5" if dark else _mix(accent, "#000000", 0.45),
        "#b9d1cd": _mix(accent, "#ffffff", 0.78),
        "#c9dedb": _mix(accent, "#ffffff", 0.85),
        "#789b97": _mix(accent, "#ffffff", 0.62),
    }
    if dark:
        mapping.update(
            {
                "#f4f7f8": "#151b22",
                "#ffffff": "#202832",
                "#f7f9f9": "#1b222b",
                "#17252a": "#edf1f5",
                "#526b70": "#bbc6d0",
                "#64777c": "#acb9c5",
                "#eef3f4": "#28323d",
                "#f2f5f6": "#28323d",
                "#f2f8f6": "#252f38",
                "#dbe4e6": "#44525f",
                "#bdcbce": "#536170",
                "#c8d5d7": "#536170",
                "#cee3dd": "#445c57",
                "#24474b": "#e2e8ee",
                "#405d61": "#c4d0db",
                "#314f53": "#c4d0db",
                "#455e65": "#c4d0db",
                "#cbd7da": "#44525f",
                "#e5f5ed": "#203e32",
                "#176345": "#8bdfb2",
                "#fff7df": "#42391f",
                "#765500": "#f4d279",
                "#e8cf86": "#8e793b",
                "#fff0ed": "#482b2b",
                "#a13a2d": "#ffafa4",
                "#8d3025": "#ffafa4",
                "#91382e": "#ffafa4",
                "#e2aaa1": "#975b54",
            }
        )
    result = re.sub(r"#[0-9a-fA-F]{6}", lambda m: mapping.get(m[0].lower(), m[0]), source)
    # Semantic success colors are independent of the user's accent.
    foreground = contrast_text(accent)
    heading = "#edf1f5" if dark else mapping["#123b3a"]
    muted = _mix(accent, "#39454f" if dark else "#ffffff", 0.65)
    result += f"""
QMainWindow, QDialog, QScrollArea, QStackedWidget, QWidget#content,
QScrollArea > QWidget > QWidget {{ background: {"#151b22" if dark else "#f4f7f8"}; }}
QTableView, QListView, QTreeView, QTextBrowser {{
background: {"#202832" if dark else "#ffffff"}; }}
QLineEdit:focus, QComboBox:focus, QPushButton:focus {{ border: 2px solid {link.name()}; }}
QPushButton#primary {{ background: {accent.name()}; border-color: {accent.name()};
color: {foreground}; }}
QPushButton#primary:focus {{ border: 2px solid {foreground}; }}
QLabel#brand, QPushButton#stepActive, QPushButton#stepActive:disabled {{ color: #ffffff; }}
QLabel#title, QLabel#sectionTitle, QLabel#reviewValue {{ color: {heading}; }}
QLabel#conceptDifference {{ color: {heading}; }}
QPushButton#primary:disabled {{ background: {muted}; border-color: {muted};
color: {contrast_text(QColor(muted))}; }}
"""
    return result


class AppearanceController(QObject):
    def __init__(self, window, base_style, settings=None):
        super().__init__(window)
        self._window, self.base_style = weakref.ref(window), base_style
        self.settings = settings if settings is not None else QSettings()
        self._applying = False
        self.current = self.load()
        QApplication.instance().installEventFilter(self)
        self.apply(self.current)

    @property
    def window(self):
        return self._window()

    def load(self):
        try:
            return Appearance(
                str(self.settings.value("appearance/mode", "light")),
                str(self.settings.value("appearance/accent", "#167c6b")),
            )
        except ValueError:
            return Appearance()

    def _owned(self, widget):
        parent = widget
        while parent is not None:
            if parent is self.window:
                return True
            parent = parent.parent()
        return False

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Polish and not self._applying:
            if hasattr(obj, "styleSheet") and obj is not self.window and self._owned(obj):
                base = obj.styleSheet()
                if base:
                    if base == self.window.styleSheet():
                        base = self.base_style
                    obj.setProperty("appearanceBaseStyle", base)
                    obj.setStyleSheet(themed_style(base, self.current))
        return False

    def apply(self, value, *, save=False):
        self.current = value
        self._applying = True
        try:
            self.window.setStyleSheet(themed_style(self.base_style, value))
            palette = QPalette()
            if value.mode == "dark":
                for role, color in (
                    (QPalette.ColorRole.Window, "#151b22"),
                    (QPalette.ColorRole.Base, "#202832"),
                    (QPalette.ColorRole.AlternateBase, "#28323d"),
                    (QPalette.ColorRole.Button, "#28323d"),
                    (QPalette.ColorRole.Text, "#edf1f5"),
                    (QPalette.ColorRole.WindowText, "#edf1f5"),
                    (QPalette.ColorRole.ButtonText, "#edf1f5"),
                    (QPalette.ColorRole.ToolTipBase, "#202832"),
                    (QPalette.ColorRole.ToolTipText, "#edf1f5"),
                ):
                    palette.setColor(role, QColor(color))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(value.accent))
            palette.setColor(
                QPalette.ColorRole.HighlightedText, QColor(contrast_text(QColor(value.accent)))
            )
            self.window.setPalette(palette)
            for widget in QApplication.allWidgets():
                if widget is self.window or not self._owned(widget):
                    continue
                base = widget.property("appearanceBaseStyle")
                if base:
                    widget.setStyleSheet(themed_style(str(base), value))
                if widget.isWindow():
                    widget.setPalette(palette)
            if save:
                self.settings.setValue("appearance/mode", value.mode)
                self.settings.setValue("appearance/accent", value.accent.lower())
                self.settings.sync()
        finally:
            self._applying = False

    def show_dialog(self):
        original = self.current
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Appearance")
        dialog.setMinimumWidth(340)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        mode = QComboBox()
        mode.addItems(["Light", "Dark"])
        mode.setCurrentIndex(original.mode == "dark")
        color = QPushButton(original.accent)
        selected = [original.accent]

        def preview():
            self.apply(Appearance("dark" if mode.currentIndex() else "light", selected[0]))
            color.setText(selected[0])

        def choose():
            value = QColorDialog.getColor(QColor(selected[0]), dialog, "Accent color")
            if value.isValid():
                selected[0] = value.name()
                preview()

        color.clicked.connect(choose)
        mode.currentIndexChanged.connect(preview)
        form.addRow("Theme", mode)
        form.addRow("Accent color", color)
        layout.addLayout(form)
        reset = QPushButton("Restore default appearance")

        def defaults():
            selected[0] = Appearance().accent
            mode.setCurrentIndex(0)
            preview()

        reset.clicked.connect(defaults)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply(self.current, save=True)
        else:
            self.apply(original)
