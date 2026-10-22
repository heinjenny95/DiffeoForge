import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from diffeoforge import landmark_correction as correction
from diffeoforge.analysis.landmarks import read_landmark_csv, write_landmark_csv


@pytest.fixture
def inputs(tmp_path):
    originals = Path(__file__).parents[1] / "examples/synthetic/meshes"
    paths = tuple(tmp_path / name for name in ("template.vtk", "subject-01.vtk", "subject-02.vtk"))
    for path in paths:
        shutil.copyfile(originals / path.name, path)
    source = tmp_path / "original-landmarks.csv"
    values = np.arange(27, dtype=np.float64).reshape(3, 3, 3) / 7
    write_landmark_csv(source, tuple(p.name for p in paths), ("LM1", "LM2", "LM3"), values)
    return source, paths, values


@pytest.mark.parametrize("indices", [(1,), (0, 2), (0, 1, 2)])
def test_merge_only_selected_coordinates_preserves_source_and_other_rows(inputs, tmp_path, indices):
    source, paths, original = inputs
    before = source.read_bytes()
    names = tuple(paths[i].name for i in indices)
    session = correction.prepare(source, paths, names, tmp_path / "project")
    points = correction.placements(session)
    for name in names:
        points[name]["LM2"] = (9.25, 10.5, 11.75)
    output = correction.save(session, points)
    labels, result = read_landmark_csv(output, tuple(p.name for p in paths))
    assert source.read_bytes() == before
    assert labels == ("LM1", "LM2", "LM3")
    for i in range(3):
        if i in indices:
            assert np.array_equal(result[i, (0, 2)], original[i, (0, 2)])
            assert np.array_equal(result[i, 1], [9.25, 10.5, 11.75])
        else:
            assert np.array_equal(result[i], original[i])
    receipt = json.loads(output.with_suffix(".correction.json").read_text())
    assert receipt["changed_specimens"] == list(names)
    assert receipt["unselected_coordinates_unchanged"]
    assert receipt["alignment_recheck_required"]
    assert not receipt["scientific_fit_started"]


@pytest.mark.parametrize("kind", ["csv", "mesh", "wrong_specimen", "missing_label", "nan"])
def test_reject_changed_inputs_or_invalid_subset_without_publishing(inputs, tmp_path, kind):
    source, paths, _ = inputs
    session = correction.prepare(source, paths, (paths[1].name,), tmp_path / "project")
    points = correction.placements(session)
    if kind == "csv":
        source.write_bytes(source.read_bytes() + b"\n")
    elif kind == "mesh":
        paths[1].write_bytes(paths[1].read_bytes() + b"\n")
    elif kind == "wrong_specimen":
        points[paths[2].name] = points[paths[1].name]
    elif kind == "missing_label":
        points[paths[1].name].pop("LM1")
    else:
        points[paths[1].name]["LM1"] = (float("nan"), 0.0, 0.0)
    with pytest.raises(ValueError):
        correction.save(session, points)
    assert not session.output.exists()


def _wait(app, predicate):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_single_specimen_editor_loads_existing_points_and_saves_without_visiting_others(
    monkeypatch, inputs, tmp_path,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog

    app = QApplication.instance() or QApplication([])
    source, paths, original = inputs
    session = correction.prepare(source, paths, (paths[1].name,), tmp_path / "project")
    dialog = LandmarkEditorDialog((paths[1],), session.output, correction=session,
                                  auto_advance_mesh=False)
    assert dialog.labels == ["LM1", "LM2", "LM3"]
    assert dialog.mesh_combo.count() == 1
    assert dialog.placements == correction.placements(session)
    assert not dialog.auto_advance_mesh_check.isChecked()
    _wait(app, lambda: dialog.canvas._model is not None)
    dialog._place_surface_point((.25, .5, .75))
    assert dialog.draft_path.is_file()
    dialog.reject()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    resumed = LandmarkEditorDialog((paths[1],), session.output, correction=session,
                                   auto_advance_mesh=False)
    assert resumed.placements[paths[1].name]["LM1"] == (.25, .5, .75)
    _wait(app, lambda: resumed.canvas._model is not None)
    for _ in range(8):
        resumed._save_and_accept()
    _wait(app, lambda: resumed.result() == QDialog.DialogCode.Accepted)
    _, values = read_landmark_csv(resumed.output_path, tuple(p.name for p in paths))
    assert np.array_equal(values[0], original[0])
    assert np.array_equal(values[2], original[2])
    assert np.array_equal(values[1, 0], [.25, .5, .75])
    assert not resumed.draft_path.exists()
    dialog.close()
    resumed.close()


def test_picker_multiple_selection_search_and_async_preparation(monkeypatch, inputs, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog

    from diffeoforge.desktop.landmark_correction import LandmarkCorrectionPicker

    app = QApplication.instance() or QApplication([])
    source, paths, _ = inputs
    picker = LandmarkCorrectionPicker(source, paths, tmp_path / "project")
    assert not picker.edit.isEnabled()
    for i in (0, 2):
        picker.list.item(i).setCheckState(Qt.CheckState.Checked)
    picker.search.setText("subject")
    assert picker.list.item(0).isHidden()
    assert picker.selected == (paths[0].name, paths[2].name)
    for _ in range(8):
        picker._prepare()
    _wait(app, lambda: picker.result() == QDialog.DialogCode.Accepted)
    assert picker.session.selected == (paths[0].name, paths[2].name)
    assert not picker.session.output.exists()
    picker.close()


def test_actual_main_button_selects_two_and_activates_complete_corrected_csv(
    monkeypatch, inputs, tmp_path,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    from diffeoforge.desktop.landmark_correction import LandmarkCorrectionPicker
    from diffeoforge.desktop.landmark_editor import LandmarkEditorDialog
    from diffeoforge.desktop.widgets import DiffeoForgeWindow

    app = QApplication.instance() or QApplication([])
    source, paths, original = inputs
    before = source.read_bytes()
    window = DiffeoForgeWindow()
    window.mesh_edit.setText(str(paths[0].parent))
    window.template_edit.setText(str(paths[0]))
    window.pattern_edit.setText("*.vtk")
    window.project_edit.setText(str(tmp_path / "project"))
    window.landmarks_edit.setText(str(source))
    window._input_preflight = object()
    window._procrustes_visual_reviewed_fingerprint = "old approval"
    observed, errors = set(), []

    def drive():
        try:
            for widget in app.topLevelWidgets():
                if not widget.isVisible() or id(widget) in observed:
                    continue
                if isinstance(widget, LandmarkCorrectionPicker):
                    observed.add(id(widget))
                    for i in (1, 2):
                        widget.list.item(i).setCheckState(Qt.CheckState.Checked)
                    widget.edit.click()
                elif isinstance(widget, LandmarkEditorDialog) and widget.canvas._model:
                    observed.add(id(widget))
                    assert widget.mesh_combo.count() == 2
                    assert widget._current_mesh_name() == paths[1].name
                    widget._place_surface_point((.5, .75, 1.0))
                    widget._save_and_accept()
        except Exception as error:
            errors.append(error)
            for widget in app.topLevelWidgets():
                if isinstance(widget, QDialog):
                    widget.reject()

    timer = QTimer()
    timer.timeout.connect(drive)
    timer.start(5)
    window.correct_landmarks_button.click()
    timer.stop()
    assert not errors
    assert len(observed) == 2
    assert window._input_preflight is None
    assert window._procrustes_visual_reviewed_fingerprint is None
    assert window._worker is None
    assert source.read_bytes() == before
    corrected = Path(window.landmarks_edit.text())
    assert corrected != source and corrected.is_file()
    _, values = read_landmark_csv(corrected, tuple(p.name for p in paths))
    assert np.array_equal(values[0], original[0])
    assert np.array_equal(values[2], original[2])
    assert np.array_equal(values[1, 0], [.5, .75, 1.0])
    assert not list((tmp_path / "project").glob("calibration/*"))
    window.close()
