"""Presentation of the chosen-fit-only control-density comparison."""

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diffeoforge.reference_control_density import rows


def render_density(dialog):
    snapshot = dialog._snapshot
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    title = QLabel("Control-point density — chosen fit only")
    title.setObjectName("sectionTitle")
    layout.addWidget(title)
    note = QLabel(
        "Compare only the chosen fit: one matched reference and two nested denser bases. "
        "All use the same pilot specimens and the same saved starting deformation. "
        "Existing control points/momenta stay in the starting basis; new points start "
        "with zero momentum. Your original anatomical approvals remain saved."
    )
    note.setWordWrap(True)
    layout.addWidget(note)
    values = rows(snapshot)
    table = QTableWidget(len(values), 5)
    table.setObjectName("controlDensityComparison")
    table.setHorizontalHeaderLabels(
        [
            "Fit",
            "Points",
            "Worst specimen p95\n(% of size)",
            "Endpoint change vs matched\nreference, p95 (% of size)",
            "Anatomical review",
        ]
    )
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for index, value in enumerate(values):
        cells = [
            value["label"],
            str(value["count"]),
            "—" if value["worst_p95"] is None else f"{value['worst_p95'] * 100:.5g}",
            "—" if value["endpoint_p95"] is None else f"{value['endpoint_p95'] * 100:.5g}",
            "Approved"
            if value["approved"] is True
            else "Rejected"
            if value["approved"] is False
            else "Required after fitting",
        ]
        for column, text in enumerate(cells):
            table.setItem(index, column, QTableWidgetItem(text))
    table.setMinimumHeight(185)
    table.setMaximumHeight(225)
    layout.addWidget(table)
    limits = QLabel(
        "Distances and endpoint changes are sampled/numerical diagnostics. "
        "Size means the original specimen's bounding-box diagonal. "
        "Lower distance alone cannot approve anatomy or establish an optimal density. "
        "Compare the finer fits with the matched reference; the original fit is retained history."
    )
    limits.setWordWrap(True)
    layout.addWidget(limits)
    dialog.content_layout.insertWidget(0, widget)
    for control in (
        dialog.find_fit_button,
        dialog.denser_model_button,
        dialog.collect_evidence_button,
        dialog.compare_options_button,
        dialog.finer_model_button,
        dialog.advanced_mode,
        dialog.afk_mode,
        dialog.adaptive_fit_search,
        dialog.outward_mode,
        dialog.continuation_disclosure,
    ):
        dialog._density_hidden_visibility[control] = not control.isHidden()
        control.hide()
    pending = [c for c in snapshot.candidates if c.status != "completed"]
    unreviewed = [
        c
        for c in snapshot.candidates
        if c.status == "completed" and c.candidate_id not in snapshot.visual_reviews
    ]
    complete = len(snapshot.candidates) - len(pending)
    if snapshot.current_stage:
        dialog.progress.setRange(0, 3)
        dialog.progress.setValue(complete)
        dialog.progress.setFormat(f"Density comparison — {complete}/3 fits complete")
    dialog.qualification_button.setVisible(bool(complete))
    if not complete:
        dialog.selection_combo.hide()
        dialog.advance_button.hide()
    if pending:
        dialog.start_button.setText(f"Fit next density — {pending[0].label}")
        dialog.start_button.setToolTip(
            f"One joint fit on all {len(snapshot.plan.selected_pilot_subjects)} pilot specimens. "
            "No other A–E options run. Pause for review afterwards."
        )
        dialog.start_button.show()
        dialog.start_button.setEnabled(
            not unreviewed and dialog._worker is None and not dialog._restoring_search
        )
        if dialog._worker is None:
            dialog.status.setText(
                "Review the completed density fit before the next comparison."
                if unreviewed
                else "Ready: run one density fit, then review its reconstructions."
            )
    dialog.advance_button.setEnabled(dialog.advance_button.isEnabled() and not pending)
