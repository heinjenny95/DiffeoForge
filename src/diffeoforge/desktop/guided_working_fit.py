"""Annotate a saved fit in the current workspace, with no historical QC writes."""

from copy import deepcopy

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton


def viewer(window, origin, parent, candidate, pairs, fit, context):
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationCandidateViewerDialog

    dialog = CalibrationCandidateViewerDialog(parent.study_directory, candidate, window,
        pairs=tuple(p for p in pairs if p.required and p.original_path.name == context["target"]),
        subject_fit=fit, read_only=True, preview_cache=origin / "display-cache")
    dialog.setWindowTitle("Work from selected saved fit")
    dialog.findChild(QLabel, "title").setText("Selected starting fit · " + context["label"])
    dialog._comparison_intro.setText(
        "Orange: original · Blue: selected saved reconstruction. Mark improvements and "
        "areas to retain here. Saving uses this fit as your working source; it does not "
        "alter its old review, approve it, prepare a trial or start fitting.")
    dialog.problem_regions = deepcopy(context["problem_regions"])
    dialog.cleared_region_subjects = set(context["cleared_region_subjects"])
    edit = QPushButton("Mark / edit multiple areas on this starting fit…")
    edit.setObjectName("secondary")
    edit.clicked.connect(dialog._mark_region)
    dialog.layout().addWidget(edit)
    save = QPushButton("Use this fit and save marked areas → next steps")
    save.setObjectName("primary")
    dialog.layout().addWidget(save)
    dialog.working_decision = None

    def ready():
        target = context["target"]
        enabled = dialog.canvas.comparison_ready and bool(dialog.display_scopes.get(target))
        edit.setEnabled(enabled)
        save.setEnabled(enabled)

    def accept():
        ready()
        if not save.isEnabled():
            return
        target = context["target"]
        dialog.working_decision = dict(reference=context["reference"],
            problem_regions={target: deepcopy(dialog.problem_regions[target])}
                if dialog.problem_regions.get(target) else {},
            inspected_subjects=[target], display_scopes={target: dialog.display_scopes[target]})
        dialog.accept()

    save.clicked.connect(accept)
    timer = QTimer(dialog)
    timer.setInterval(100)
    timer.timeout.connect(ready)
    timer.start()
    dialog.finished.connect(timer.stop)
    ready()
    return dialog


def show(window, key, prepared):
    parent, pairs, fit, candidate, context = prepared
    dialog = viewer(window, key[1], parent, candidate, pairs, fit, context)
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.working_decision:
            window._start_pilot(adaptive=False,
                guided_action=("adaptive_working_start", key[3], dialog.working_decision))
    finally:
        dialog.deleteLater()
