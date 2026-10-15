"""Comparison of saved singleton screens, with an explicit single joint choice."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.desktop.reference_calibration_presentation import candidate_option_label


class ScreeningChoicePanel(QWidget):
    choice_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Compare screened options, then choose one joint test")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Option", "Your review", "Sampled p95 ↓", "Median ↓",
            "Regularity", "Area distortion", "Sampling Δ", "Optimizer stop",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(180)
        self.table.setMaximumHeight(240)
        layout.addWidget(self.table)
        self.notice = QLabel(
            "Sorted by the largest sampled p95 distance across the screening specimens "
            "(lower is closer, in project coordinates). Regularity and area distortion are "
            "context, not fit scores. Small distance differences can reflect sampling. "
            "These frozen-reference screens do not establish the best joint atlas. "
            "Your approvals remain saved; only the option you choose below is tested "
            "with all pilot specimens, followed by separate all-specimen visual QC."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.choice = QComboBox()
        self.choice.setObjectName("screenJointChoice")
        self.choice.setAccessibleName("Choose one kept option for the joint test")
        self.choice.currentIndexChanged.connect(lambda _index: self.choice_changed.emit())
        layout.addWidget(self.choice)
        self._stage_key = None

    def present(self, snapshot, *, running=False):
        state = snapshot.early_screening
        stage_key = (str(snapshot.study_directory), state["stage_id"])
        previous = self.choice.currentData() if self._stage_key == stage_key else None
        self._stage_key = stage_key
        letters = {c.candidate_id: candidate_option_label(i)
                   for i, c in enumerate(snapshot.current_stage.candidates, 1)}
        rows = sorted(state["comparison"], key=lambda r: (
            r["p95"] is None, r["p95"] if r["p95"] is not None else 0,
            state["candidate_ids"].index(r["candidate_id"]),
        ))
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            def number(key, row=row):
                return "—" if row[key] is None else f"{row[key]:.6g}"
            values = (
                letters[row["candidate_id"]], row["review"], number("p95"), number("median"),
                number("deformation_energy"), number("distortion_p95"),
                "—" if row["resampling_sensitivity"] is None
                else f"{row['resampling_sensitivity']:.2%}",
                "Tolerance" if row["converged"] else ", ".join(row["stop_signals"])
                if row["completed"] else "No completed fit",
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.addItem("Choose one kept option…", None)
        for cid in state["kept"]:
            self.choice.addItem(f"Option {letters[cid]}", cid)
        selected = state.get("joint_selection") or previous
        self.choice.setCurrentIndex(max(0, self.choice.findData(selected)))
        self.choice.setEnabled(not running and not state.get("joint_selection"))
        self.choice.blockSignals(False)

    @property
    def selected_candidate_id(self):
        return self.choice.currentData()
