"""Direct, non-executing selection of mandatory pilot subjects."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PilotSubjectPicker(QWidget):
    """Select from the analyzed cohort, never from arbitrary typed file paths.

    The template is already part of every pilot and is not a target subject.
    A changed cohort clears the previous manual selection with a visible notice;
    re-analysis of the same inputs preserves it.
    """

    selectionChanged = Signal()

    def __init__(self, parent: QWidget | None = None, *, maximum: int = 20) -> None:
        super().__init__(parent)
        self.maximum = maximum
        self._cohort_key: tuple[str, ...] | None = None
        self._names: tuple[str, ...] = ()
        self._selected: tuple[str, ...] = ()
        self._notice = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setObjectName("referencePilotSubjectCombo")
        self.combo.setAccessibleName("Choose a mesh to include in the pilot")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(20)
        self.combo.lineEdit().setPlaceholderText("Choose or search a mesh…")
        self.combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.combo.editTextChanged.connect(self._refresh_controls)
        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("secondary")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.combo, 1)
        row.addWidget(self.add_button)
        layout.addLayout(row)
        selected_row = QHBoxLayout()
        self.selected_list = QListWidget()
        self.selected_list.setAccessibleName("Manually included pilot meshes")
        self.selected_list.setMaximumHeight(100)
        self.selected_list.currentRowChanged.connect(self._refresh_controls)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("secondary")
        self.remove_button.clicked.connect(self._remove)
        selected_row.addWidget(self.selected_list, 1)
        selected_row.addWidget(self.remove_button)
        layout.addLayout(selected_row)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.setToolTip(
            "All target meshes from the current aligned-mesh analysis are available. "
            "The template is already included separately. Manual choices occupy slots "
            "within the pilot total; remaining slots use automatic shape coverage."
        )
        self._refresh_controls()

    @property
    def selected_filenames(self) -> tuple[str, ...]:
        return self._selected

    def set_subjects(self, filenames: Sequence[str], *, cohort_key: tuple[str, ...]) -> None:
        names = tuple(sorted(filenames, key=str.casefold))
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Pilot mesh filenames must be unique ignoring case")
        changed_cohort = self._cohort_key is not None and (
            self._cohort_key != cohort_key or self._names != names
        )
        cleared = changed_cohort and bool(self._selected)
        if changed_cohort:
            self._selected = ()
            self._notice = "Selection cleared: mesh cohort changed. " if cleared else ""
        self._cohort_key = cohort_key
        self._names = names
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(names)
        self.combo.setCurrentIndex(-1)
        self.combo.blockSignals(False)
        self._refresh_list()
        if cleared:
            self.selectionChanged.emit()

    def _candidate(self) -> str | None:
        value = self.combo.currentText().strip().casefold()
        return next((name for name in self._names if name.casefold() == value), None)

    def _refresh_controls(self, *_args: object) -> None:
        candidate = self._candidate()
        self.add_button.setEnabled(
            candidate is not None
            and candidate not in self._selected
            and len(self._selected) < self.maximum
        )
        self.remove_button.setEnabled(self.selected_list.currentRow() >= 0)
        self.selected_list.setVisible(bool(self._selected))
        self.remove_button.setVisible(bool(self._selected))
        count = len(self._selected)
        self.hint.setText(
            self._notice
            + (
                f"{count} manually included · counts toward the pilot total."
                if count
                else "Optional: always include these meshes; other slots are chosen automatically."
            )
            + (f" Limit: {self.maximum}." if count == self.maximum else "")
        )

    def _refresh_list(self) -> None:
        self.selected_list.clear()
        self.selected_list.addItems(self._selected)
        if self._selected:
            self.selected_list.setCurrentRow(len(self._selected) - 1)
        self._refresh_controls()

    def _add(self) -> None:
        candidate = self._candidate()
        if (
            not self.isEnabled()
            or candidate is None
            or candidate in self._selected
            or len(self._selected) >= self.maximum
        ):
            return
        self._selected = tuple(sorted((*self._selected, candidate), key=str.casefold))
        self._notice = ""
        self._refresh_list()
        self.selectionChanged.emit()

    def _remove(self) -> None:
        row = self.selected_list.currentRow()
        if not self.isEnabled() or row < 0:
            return
        self._selected = self._selected[:row] + self._selected[row + 1 :]
        self._notice = ""
        self._refresh_list()
        self.selectionChanged.emit()
