"""One editing session keeps independent instructions and atomic cancellation."""

from copy import deepcopy

import numpy as np
import pytest

from diffeoforge.pilot_regions import validate


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_full_review_geometry import model

    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.desktop.region_marking_geometry import prepare_region_marking_mesh

    app = QApplication.instance() or QApplication([])
    original = prepare_region_marking_mesh(model(tmp_path / "original.vtk", False))
    dialog = RegionFeedbackDialog(original)
    dialog.show()
    yield dialog
    dialog.close()
    app.processEvents()


def add(dialog, point, action="problem:detail"):
    dialog.canvas.surfacePointPicked.emit(point)
    dialog.action.setCurrentIndex(dialog.action.findData(action))


def test_add_edit_reopen_mixed_instructions_without_reassigning_other_points(editor):
    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog

    add(editor, (-.5, 0, 0))
    add(editor, (.5, 0, 0), "fixed")
    add(editor, (0, .5, 0), "preserve")
    before = deepcopy(editor._rows)
    editor.listing.setCurrentRow(0)
    editor.size.setValue(18)
    assert editor._rows[1:] == before[1:]
    editor._save()
    rows = validate({"original": editor.regions}, {"original": editor.model.sha256})["original"]
    assert [(r["purpose"], r["symptom"]) for r in rows] == [
        ("problem", "detail"), ("fixed", "detail"), ("preserve", "detail")]
    reopened = RegionFeedbackDialog(editor.marking, regions=rows)
    for i in (2, 0, 1):
        reopened.listing.setCurrentRow(i)
    assert reopened._rows == rows
    assert set(reopened.canvas._markers) == {"A", "B", "C"}
    reopened._save()
    assert reopened.regions == rows
    reopened.close()


def test_cancel_move_remove_and_explicit_clear_are_atomic(editor):
    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog

    add(editor, (0, 0, 0))
    editor._save()
    rows = deepcopy(editor.regions)
    edit = RegionFeedbackDialog(editor.marking, regions=rows)
    edit.action.setCurrentIndex(edit.action.findData("fixed"))
    edit.move.setChecked(True)
    edit.canvas.surfacePointPicked.emit((.4, .4, 0))
    assert len(edit._rows) == 1 and edit._rows[0]["center"] == [.4, .4, 0]
    edit.reject()
    assert edit.regions is None and rows == editor.regions
    edit._remove()
    assert edit.save.isEnabled()
    edit._save()
    assert edit.regions == []


def test_independent_boxes_and_all_areas_are_visible(editor):
    add(editor, (-.5, 0, 0), "fixed")
    editor.shape.setCurrentIndex(1)
    editor.axes[0].setValue(12)
    box = deepcopy(editor._rows[0])
    add(editor, (.5, 0, 0))
    assert editor._rows[0] == box and editor._rows[1].get("shape") is None
    v, f = np.asarray(editor.model.vertices), np.asarray(editor.model.triangles)
    colors = editor.canvas._surface_layer(v, f).face_colors
    assert np.any(np.all(colors[:, :3] == (129, 170, 149), axis=1))
    assert np.any(np.all(colors[:, :3] == (223, 94, 103), axis=1))


def test_empty_patch_blocks_batch_save_and_limit_still_allows_editing(editor):
    add(editor, (500, 500, 500))
    assert not editor.save.isEnabled()
    editor._remove()
    for i in range(8):
        add(editor, (i * .05, 0, 0))
    add(editor, (.7, .7, 0))
    assert len(editor._rows) == 8
    editor.listing.setCurrentRow(2)
    editor.action.setCurrentIndex(editor.action.findData("fixed"))
    assert editor._rows[2]["purpose"] == "fixed"


def test_untouched_legacy_record_is_not_rounded_on_selection(editor):
    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog

    add(editor, (0, 0, 0))
    old = deepcopy(editor._rows[0])
    old["radius"] = editor.diagonal * .083167
    old.pop("purpose")
    old["version"] = "surface-region-v1"
    edit = RegionFeedbackDialog(editor.marking, regions=[old])
    edit._save()
    assert edit.regions == [old]


def test_correct_fit_clicks_original_and_fit_and_uses_only_confirmed_diagnosis(
        tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from test_full_review_geometry import wait
    from test_marked_area_diagnosis import plane

    from diffeoforge.desktop.landmark_3d_widget import pick_surface_point
    from diffeoforge.desktop.pilot_preview import load_pilot_preview
    from diffeoforge.desktop.region_feedback_dialog import RegionFeedbackDialog
    from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh
    from diffeoforge.mesh import sha256_file, write_vtk_polydata

    app = QApplication.instance() or QApplication([])
    original_path, fit_path = (tmp_path / name for name in ("original.vtk", "fit.vtk"))
    points, faces = plane(0, 42)
    extra = points + [0, 0, .05]
    write_vtk_polydata(original_path, points, faces, title="Original surface")
    write_vtk_polydata(fit_path, np.vstack((points, extra)),
                       np.vstack((faces, faces + len(points))), title="Extra fitted surface")
    original_sha, fit_sha = sha256_file(original_path), sha256_file(fit_path)
    original = load_region_marking_mesh(original_path, original_sha)
    dialog = RegionFeedbackDialog(
        original, rotation=np.eye(3), fit_preview=load_pilot_preview(fit_path),
    )
    dialog.show()

    def click_centre(offset=0):
        canvas = dialog.canvas
        wait(app, lambda: canvas.picking_ready)
        pos = QPoint(canvas.width() // 2 + offset, canvas.height() // 2)
        assert canvas.pick_at(QPointF(pos)) is not None
        assert pick_surface_point(canvas._surface(displayed=True), (pos.x(), pos.y())) is not None
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pos)

    try:
        assert dialog.view.currentData() == "overlay"
        assert not dialog.canvas.original_detail.isChecked()
        click_centre()
        first = dialog._rows[0]
        assert first["center"][2] == pytest.approx(0)
        assert first["symptom"] == "unsure"
        wait(app, dialog.use_suggestion.isVisible)
        assert "may include extra surface" in dialog.finding.text()
        assert first["symptom"] == "unsure"
        dialog.use_suggestion.click()
        assert first["symptom"] == "distortion"
        old_key = dialog._diagnosis_key

        dialog.view.setCurrentIndex(dialog.view.findData("fit"))
        assert dialog.view.currentData() == "fit"
        click_centre(offset=9)
        second = dialog._rows[1]
        assert second["center"][2] == pytest.approx(.05)
        assert second["symptom"] == "unsure"
        dialog.action.setCurrentIndex(dialog.action.findData("problem:distortion"))
        assert second["symptom"] == "distortion" and second["source_sha256"] == original_sha
        dialog._diagnosis_ready(old_key, {"symptom": "missing", "message": "Stale result"})
        assert "Stale result" not in dialog.finding.text()
        assert second["symptom"] == "distortion"
        protect_mode = next(b for b in dialog.click_modes.buttons()
                            if b.text() == "Green · Keep unchanged")
        protect_mode.click()
        assert dialog.view.currentData() == "original"
        click_centre(offset=-9)
        protected = dialog._rows[2]
        assert protected["purpose"] == "fixed"
        assert protected["center"][2] == pytest.approx(0)
        colors = dialog.canvas._marker_colors
        assert colors["A"] == colors["B"] != colors["C"]
        assert dialog.save.isEnabled()
        dialog.save.click()
        assert dialog.regions == [first, second, protected]
        assert sha256_file(original_path) == original_sha
        assert sha256_file(fit_path) == fit_sha
    finally:
        dialog.close()
        app.processEvents()
