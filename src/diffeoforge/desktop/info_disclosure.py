"""Compact, accessible progressive-disclosure controls for desktop guidance."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class InfoDisclosure(QWidget):
    """Keep supporting guidance available without making it permanently visible."""

    def __init__(
        self,
        title: str,
        content: QWidget | str,
        *,
        accessible_name: str | None = None,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("infoDisclosureButton")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setAccessibleName(accessible_name or f"Information: {title}")
        self.toggle_button.setToolTip(f"Show or hide {title.lower()}.")
        self.toggle_button.toggled.connect(self._set_expanded)
        button_row.addWidget(self.toggle_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.panel = QFrame()
        self.panel.setObjectName("infoDisclosurePanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(11, 8, 11, 8)
        if isinstance(content, str):
            label = QLabel(content)
            label.setObjectName("infoDisclosureText")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.content_widget = label
        else:
            self.content_widget = content
        panel_layout.addWidget(self.content_widget)
        layout.addWidget(self.panel)
        self._set_expanded(expanded)

    @Slot(bool)
    def _set_expanded(self, expanded: bool) -> None:
        self.panel.setVisible(expanded)
        self.toggle_button.setText(
            f"ⓘ Hide {self.title.lower()}" if expanded else f"ⓘ {self.title}"
        )

