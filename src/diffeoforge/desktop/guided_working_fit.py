"""Annotate a saved fit in the current workspace, with no historical QC writes."""

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton


def viewer(window, origin, parent, candidate, pairs, fit, context):
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationCandidateViewerDialog

    pairs = tuple(p for p in pairs if p.required and p.original_path.name == context["target"])
    hint = context.get("view_hint")
    if (hint and len(pairs) == 1 and hint["reference"] == context["reference"]
            and hint["hashes"] == (pairs[0].original_sha256, pairs[0].reconstruction_sha256)):
        pairs = (replace(pairs[0], inspection_markers=hint["markers"]),)
    else:
        hint = None
    dialog = CalibrationCandidateViewerDialog(parent.study_directory, candidate, window,
        pairs=pairs,
        subject_fit=fit, read_only=True, compact_review=True,
        preview_cache=origin / "display-cache")
    dialog.setWindowTitle("Work from selected saved fit")
    dialog.findChild(QLabel, "title").setText("Selected starting fit · " + context["label"])
    dialog._comparison_intro.setText(
        "Orange: original · Blue: saved reconstruction. Use Improve on the areas that "
        "still need work and Retain on the areas that now look right. Save this fit and "
        "the marks as the starting point for your next test.")
    if draft := context.get("partial_draft"):
        detail = (f" · {draft['suggested']} suggested Retain"
                  if draft["suggested"] else "")
        dialog._comparison_intro.setText(
            f"{draft['remaining']} remaining Improve{detail}. Review the proposed areas "
            "on this saved fit and edit them if needed. Saving confirms the displayed marks.")
    if hint:
        # The normal initial pair load resets the camera before the hand-off.
        # Later full-detail loads must keep the user's new view.
        def restore_view(_key, _models):
            dialog._mesh_loader.loaded.disconnect(restore_view)
            dialog.canvas.set_linked_camera(hint["camera"])

        dialog._mesh_loader.loaded.connect(restore_view)
        if hint["markers"]:
            label = QLabel(
                "Numbered areas are visual guides. Use the marking tool to select areas."
            )
            label.setWordWrap(True)
            dialog.layout().addWidget(label)
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
