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

    app = QApplication.instance() or QApplication([])
    dialog = RegionFeedbackDialog(model(tmp_path / "original.vtk", False))
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
    reopened = RegionFeedbackDialog(editor.model, regions=rows)
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
    edit = RegionFeedbackDialog(editor.model, regions=rows)
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
    assert np.any(np.all(colors[:, :3] == (58, 119, 193), axis=1))
    assert np.any(np.all(colors[:, :3] == (242, 115, 45), axis=1))


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
    edit = RegionFeedbackDialog(editor.model, regions=[old])
    edit._save()
    assert edit.regions == [old]
